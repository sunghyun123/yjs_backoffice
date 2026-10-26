"""하루치 메일 조회 — MCP 중계가 "어제 온 메일 요약해줘"에 쓰는 읽기 전용 경로.

대시보드 수집기(`MailCollector`)는 안 읽은 메일 헤더만 보지만, 이 모듈은
지정한 KST 하루 동안 '받은' 메일 전부를 본문 일부까지 읽는다. 저장하지 않는다.
"""

from __future__ import annotations

import base64
import html
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as fixed_offset
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from app.domain import MailAccountDayStatus, MailDayResult, MailMessage
from app.mail import (
    ImapConnection,
    ImapFactory,
    MailAccount,
    decode_mime_header,
    default_imap_factory,
)


logger = logging.getLogger(__name__)

# IMAP 날짜 문법은 영어 월 약어만 받는다. strftime("%b")는 OS 로캘을 따라가므로 쓰지 않는다.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_INTERNALDATE_RE = re.compile(
    rb'INTERNALDATE " ?(?P<d>\d{1,2})-(?P<mon>[A-Za-z]{3})-(?P<y>\d{4}) '
    rb'(?P<hh>\d{2}):(?P<mm>\d{2}):(?P<ss>\d{2}) (?P<sign>[+-])(?P<oh>\d{2})(?P<om>\d{2})"'
)
_UID_RE = re.compile(rb"\bUID (\d+)")
_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
# SPECIAL-USE 표시가 없는 서버(네이버·다우 등)를 위해 이름으로도 거른다.
_SKIP_FLAGS = frozenset(
    {"\\sent", "\\drafts", "\\trash", "\\all", "\\flagged", "\\important"}
)
_SKIP_NAMES = frozenset(
    {
        "sent", "sent mail", "sent messages", "sent items",
        "보낸메일함", "보낸편지함", "보낸 메일함",
        "drafts", "draft", "임시보관함", "임시 보관함",
        "trash", "deleted", "deleted messages", "deleted items", "휴지통",
    }
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def imap_date(day: date) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def parse_internaldate(line: bytes) -> datetime | None:
    """서버가 '받은 시각'(INTERNALDATE)을 시간대 포함 datetime으로 읽는다.

    imaplib.Internaldate2tuple은 결과를 이 PC의 로컬 시간대로 바꿔버리므로 쓰지 않는다.
    """
    match = _INTERNALDATE_RE.search(line)
    if not match:
        return None
    try:
        month = _MONTHS.index(match["mon"].decode().title()) + 1
    except ValueError:
        return None
    offset = timedelta(hours=int(match["oh"]), minutes=int(match["om"]))
    if match["sign"] == b"-":
        offset = -offset
    return datetime(
        int(match["y"]),
        month,
        int(match["d"]),
        int(match["hh"]),
        int(match["mm"]),
        int(match["ss"]),
        tzinfo=fixed_offset(offset),
    )


def html_to_text(value: str) -> str:
    text = _SCRIPT_RE.sub(" ", value)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(_TAG_RE.sub(" ", text))
    return text


def normalize_text(value: str) -> str:
    lines = (_SPACE_RE.sub(" ", line).strip() for line in value.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def extract_body_text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError, ValueError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if not isinstance(content, str):
        return ""
    if part.get_content_subtype() == "html":
        content = html_to_text(content)
    return normalize_text(content)


@dataclass(frozen=True)
class MailFolder:
    raw_name: str  # 서버에 다시 보낼 이름 (modified UTF-7 그대로)
    name: str  # 사람이 읽는 이름
    flags: frozenset[str]


@dataclass(frozen=True)
class _Candidate:
    folder: MailFolder
    uid: bytes
    received: datetime


def decode_modified_utf7(value: str) -> str:
    """IMAP 폴더 이름의 한글 표기(RFC 3501 modified UTF-7)를 사람이 읽는 글자로 바꾼다."""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        end = value.find("-", index) if char == "&" else -1
        if end == -1:
            result.append(char)
            index += 1
            continue
        chunk = value[index + 1 : end]
        if not chunk:
            result.append("&")
        else:
            padded = chunk.replace(",", "/") + "=" * (-len(chunk) % 4)
            result.append(base64.b64decode(padded).decode("utf-16-be"))
        index = end + 1
    return "".join(result)


def parse_list_line(line: bytes | tuple) -> MailFolder | None:
    if isinstance(line, tuple):  # 이름이 literal({n})로 오는 경우: (머리, 이름)
        head, name_bytes = line[0], line[1]
        head = re.sub(rb"\{\d+\}$", b"", head).rstrip()
        match = _LIST_RE.match(head + b' "' + name_bytes + b'"')
    else:
        match = _LIST_RE.match(line)
    if not match:
        return None
    raw = match["name"].decode("utf-8", errors="replace")
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    flags = frozenset(flag.lower() for flag in match["flags"].decode().split())
    return MailFolder(raw_name=raw, name=decode_modified_utf7(raw), flags=flags)


def choose_folders(folders: list[MailFolder]) -> tuple[list[MailFolder], bool]:
    """읽을 폴더와 '전체보관함 방식인지'를 정한다.

    Gmail처럼 \\All 폴더가 있으면 모든 메일이 거기 한 번씩만 있으므로 그것 + 스팸함만 본다
    (라벨 폴더를 다 돌면 같은 메일을 라벨 수만큼 읽는다). 단 \\All에는 보낸 메일도 섞여 있다.
    없으면 보낸편지함·임시보관함·휴지통을 뺀 모든 폴더를 본다.
    """
    selectable = [
        folder for folder in folders if not folder.flags & {"\\noselect", "\\nonexistent"}
    ]
    all_mail = [folder for folder in selectable if "\\all" in folder.flags]
    if all_mail:
        junk = [folder for folder in selectable if "\\junk" in folder.flags]
        return all_mail[:1] + junk, True
    chosen = []
    for folder in selectable:
        if folder.flags & _SKIP_FLAGS:
            continue
        leaf = re.split(r"[/.]", folder.name)[-1].strip().lower()
        if leaf in _SKIP_NAMES:
            continue
        chosen.append(folder)
    return chosen, False


def quote_mailbox(raw_name: str) -> str:
    return '"' + raw_name.replace("\\", "\\\\").replace('"', '\\"') + '"'


class MailDayReader:
    def __init__(
        self,
        accounts: list[MailAccount],
        timezone: ZoneInfo,
        *,
        max_messages_per_account: int = 100,
        fetch_bytes: int = 200_000,
        fetch_batch_size: int = 20,
        body_chars: int = 3000,
        timeout_seconds: int = 20,
        imap_factory: ImapFactory = default_imap_factory,
    ) -> None:
        self._accounts = accounts
        self._timezone = timezone
        self._max_messages = max_messages_per_account
        self._fetch_bytes = fetch_bytes
        self._fetch_batch_size = fetch_batch_size
        self._body_chars = body_chars
        self._timeout_seconds = timeout_seconds
        self._imap_factory = imap_factory

    @property
    def configured(self) -> bool:
        return bool(self._accounts)

    def window(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self._timezone)
        return start, start + timedelta(days=1)

    def read_day(self, day: date) -> MailDayResult:
        start, end = self.window(day)
        statuses: list[MailAccountDayStatus] = []
        messages: list[MailMessage] = []
        for account in self._accounts:
            try:
                account_messages, truncated = self._read_account(account, start, end)
            except (imaplib.IMAP4.error, OSError, ValueError) as exc:
                # 실패한 계정을 결과에 남긴다. 빠진 계정이 '메일 0통'으로 보이면 안 된다.
                logger.warning("메일 계정 %s 하루 조회 실패: %s", account.name, type(exc).__name__)
                statuses.append(MailAccountDayStatus(account=account.name, ok=False))
                continue
            statuses.append(
                MailAccountDayStatus(
                    account=account.name,
                    ok=True,
                    count=len(account_messages),
                    truncated=truncated,
                )
            )
            messages.extend(account_messages)
        messages.sort(key=lambda item: item.received_at)
        return MailDayResult(
            date=day,
            timezone=str(self._timezone),
            window_start=start,
            window_end=end,
            fetched_at=datetime.now(self._timezone),
            configured=self.configured,
            accounts=statuses,
            messages=messages,
        )

    def _read_account(
        self,
        account: MailAccount,
        start: datetime,
        end: datetime,
    ) -> tuple[list[MailMessage], bool]:
        connection = self._imap_factory(account.host, account.port, self._timeout_seconds)
        try:
            status, _ = connection.login(account.username, account.password)
            if status != "OK":
                raise ValueError("IMAP 로그인 실패")
            folders, all_mail_mode = choose_folders(self._list_folders(connection))
            if not folders:
                raise ValueError("읽을 메일 폴더가 없습니다")
            candidates: list[_Candidate] = []
            for folder in folders:
                self._select(connection, folder)
                uids = self._search_candidates(connection, start, end)
                candidates.extend(
                    _Candidate(folder, uid, received)
                    for uid, received in self._internaldates(connection, uids)
                    if start <= received < end
                )
            candidates.sort(key=lambda item: item.received)
            truncated = len(candidates) > self._max_messages
            # 넘치면 최근 것을 남기고, truncated로 잘렸다는 사실을 알린다.
            selected = candidates[-self._max_messages :]
            own_address = account.username.strip().lower() if all_mail_mode else ""
            return self._fetch_messages(connection, selected, account, own_address), truncated
        finally:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _list_folders(self, connection: ImapConnection) -> list[MailFolder]:
        status, data = connection.list()
        if status != "OK":
            raise ValueError("폴더 목록 조회 실패")
        folders = [parse_list_line(line) for line in data or [] if line]
        return [folder for folder in folders if folder is not None]

    def _select(self, connection: ImapConnection, folder: MailFolder) -> None:
        # readonly: 조회만으로 '읽음' 표시가 바뀌지 않게 한다.
        status, _ = connection.select(quote_mailbox(folder.raw_name), readonly=True)
        if status != "OK":
            raise ValueError("메일 폴더 선택 실패")

    def _search_candidates(
        self,
        connection: ImapConnection,
        start: datetime,
        end: datetime,
    ) -> list[bytes]:
        # IMAP SINCE/BEFORE는 시각 없이 '메일 서버 기준 날짜'로만 비교한다.
        # 서버 시간대가 무엇이든 놓치지 않도록 앞뒤 하루씩 넓혀 받고, 정확한 경계는 아래에서 KST로 자른다.
        since = (start - timedelta(days=1)).date()
        before = (end + timedelta(days=1)).date()
        # UID: 검색과 조회 사이에 다른 기기가 메일을 지워도 번호가 밀리지 않는 고유 번호.
        status, data = connection.uid(
            "SEARCH", None, "SINCE", imap_date(since), "BEFORE", imap_date(before)
        )
        if status != "OK":
            raise ValueError("날짜 검색 실패")
        return data[0].split() if data and data[0] else []

    def _internaldates(
        self,
        connection: ImapConnection,
        uids: list[bytes],
    ) -> list[tuple[bytes, datetime]]:
        if not uids:
            return []
        status, data = connection.uid("FETCH", b",".join(uids), "(INTERNALDATE)")
        if status != "OK":
            raise ValueError("수신 시각 조회 실패")
        results: list[tuple[bytes, datetime]] = []
        for part in data:
            line = part[0] if isinstance(part, tuple) else part
            if not isinstance(line, bytes) or line == b")":
                continue
            uid = _UID_RE.search(line)
            received = parse_internaldate(line)
            if uid is None or received is None:
                # 시각을 못 읽은 메일은 어느 날인지 판정할 수 없다. 조용히 버리지 않고 실패로 올린다.
                raise ValueError("수신 시각 해석 실패")
            results.append((uid.group(1), received.astimezone(self._timezone)))
        return results

    def _fetch_messages(
        self,
        connection: ImapConnection,
        candidates: list[_Candidate],
        account: MailAccount,
        own_address: str,
    ) -> list[MailMessage]:
        messages: list[MailMessage] = []
        seen_ids: set[str] = set()
        by_folder: dict[MailFolder, list[_Candidate]] = {}
        for candidate in candidates:
            by_folder.setdefault(candidate.folder, []).append(candidate)
        for folder, items in by_folder.items():
            self._select(connection, folder)
            received_by_uid = {item.uid: item.received for item in items}
            # 한 통씩 왕복하지 않고 묶어서 받는다(N+1 회피). 묶음 크기로 응답 한 번의 크기를 제한한다.
            for offset in range(0, len(items), self._fetch_batch_size):
                batch = items[offset : offset + self._fetch_batch_size]
                for uid, raw in self._fetch_raw(connection, [item.uid for item in batch]):
                    received = received_by_uid.get(uid)
                    if received is None:
                        continue
                    message = self._to_message(raw, received, account, folder)
                    if own_address and message.sender_address.lower() == own_address:
                        continue  # 전체보관함에 섞인 내가 보낸 메일
                    message_id = (message.message_id or "").strip()
                    if message_id:
                        if message_id in seen_ids:
                            continue
                        seen_ids.add(message_id)
                    messages.append(message)
        messages.sort(key=lambda item: item.received_at)
        return messages

    def _fetch_raw(
        self,
        connection: ImapConnection,
        uids: list[bytes],
    ) -> list[tuple[bytes, bytes]]:
        # BODY.PEEK: 읽어도 '읽음' 표시를 안 남긴다. <0.N>: 첨부가 커도 앞부분만 받는다.
        status, data = connection.uid(
            "FETCH", b",".join(uids), f"(BODY.PEEK[]<0.{self._fetch_bytes}>)"
        )
        if status != "OK":
            raise ValueError("메일 본문 조회 실패")
        results: list[tuple[bytes, bytes]] = []
        for part in data:
            if not (isinstance(part, tuple) and isinstance(part[1], bytes)):
                continue
            uid = _UID_RE.search(part[0])
            if uid is None:
                raise ValueError("본문 응답에 UID가 없습니다")
            results.append((uid.group(1), part[1]))
        return results

    def _to_message(
        self,
        raw: bytes,
        received: datetime,
        account: MailAccount,
        folder: MailFolder,
    ) -> MailMessage:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        sender_name, sender_address = parseaddr(decode_mime_header(message.get("From")))
        try:
            body = extract_body_text(message)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - 잘린 MIME 등 본문 해석 실패는 그 한 통의 본문만 비운다.
            body = ""
        body_truncated = len(body) > self._body_chars or len(raw) >= self._fetch_bytes
        return MailMessage(
            account=account.name,
            folder=folder.name,
            message_id=str(message.get("Message-ID") or "") or None,
            sender=sender_name.strip() or sender_address.strip() or "발신자 없음",
            sender_address=sender_address.strip(),
            subject=decode_mime_header(message.get("Subject")) or "(제목 없음)",
            received_at=received,
            body=body[: self._body_chars],
            body_truncated=body_truncated,
        )
