from __future__ import annotations

import imaplib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from app.domain import MailItem, MailSnapshot


MailAccountName = Literal["daou", "gmail", "naver"]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailAccount:
    name: MailAccountName
    host: str
    port: int
    username: str
    password: str
    mailbox_url: str


class ImapConnection(Protocol):
    def login(self, user: str, password: str): ...

    def select(self, mailbox: str = "INBOX", readonly: bool = False): ...

    def search(self, charset, *criteria): ...

    def fetch(self, message_set, message_parts): ...

    def logout(self): ...


ImapFactory = Callable[[str, int, int], ImapConnection]


def default_imap_factory(host: str, port: int, timeout: int) -> ImapConnection:
    return imaplib.IMAP4_SSL(host, port, timeout=timeout)


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for content, charset in decode_header(value):
        if isinstance(content, bytes):
            for encoding in (charset, "utf-8", "cp949"):
                if not encoding:
                    continue
                try:
                    parts.append(content.decode(encoding, errors="strict"))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
            else:
                parts.append(content.decode("utf-8", errors="replace"))
        else:
            parts.append(content)
    return "".join(parts).strip()


class MailCollector:
    def __init__(
        self,
        accounts: list[MailAccount],
        timezone: ZoneInfo,
        refresh_interval_sec: int,
        *,
        max_items_per_account: int = 10,
        timeout_seconds: int = 10,
        imap_factory: ImapFactory = default_imap_factory,
    ) -> None:
        self._accounts = accounts
        self._timezone = timezone
        self._refresh_interval_sec = refresh_interval_sec
        self._max_items_per_account = max_items_per_account
        self._timeout_seconds = timeout_seconds
        self._imap_factory = imap_factory
        self._date_parse_failures = 0

    @property
    def configured(self) -> bool:
        return bool(self._accounts)

    def collect(self) -> MailSnapshot:
        if not self._accounts:
            return MailSnapshot(refresh_interval_sec=self._refresh_interval_sec)

        fetched_at = datetime.now(self._timezone)
        self._date_parse_failures = 0
        unread_by_account: dict[str, int] = {}
        items: list[MailItem] = []
        failed_accounts: list[str] = []

        for account in self._accounts:
            try:
                count, account_items = self._collect_account(account)
                unread_by_account[account.name] = count
                items.extend(account_items)
            except (imaplib.IMAP4.error, OSError, ValueError):
                unread_by_account[account.name] = 0
                failed_accounts.append(account.name)

        items.sort(
            key=lambda item: item.at or datetime.min.replace(tzinfo=self._timezone),
            reverse=True,
        )
        error = (
            f"{len(failed_accounts)}개 메일 계정 갱신 실패"
            if failed_accounts
            else None
        )
        if self._date_parse_failures:
            logger.warning(
                "메일 날짜 헤더 %d건을 해석하지 못했습니다.",
                self._date_parse_failures,
            )
        return MailSnapshot(
            refresh_interval_sec=self._refresh_interval_sec,
            fetched_at=fetched_at,
            stale=bool(failed_accounts),
            error=error,
            unread_total=sum(unread_by_account.values()),
            unread_by_account=unread_by_account,
            items=items[: max(1, self._max_items_per_account * len(self._accounts))],
        )

    def _collect_account(self, account: MailAccount) -> tuple[int, list[MailItem]]:
        connection = self._imap_factory(
            account.host,
            account.port,
            self._timeout_seconds,
        )
        try:
            status, _ = connection.login(account.username, account.password)
            if status != "OK":
                raise ValueError("IMAP 로그인 실패")
            status, _ = connection.select("INBOX", readonly=True)
            if status != "OK":
                raise ValueError("INBOX 선택 실패")
            status, data = connection.search(None, "UNSEEN")
            if status != "OK":
                raise ValueError("안 읽은 메일 검색 실패")
            message_ids = data[0].split() if data and data[0] else []
            selected_ids = message_ids[-self._max_items_per_account :]
            items = [
                self._fetch_header(connection, message_id, account)
                for message_id in reversed(selected_ids)
            ]
            return len(message_ids), items
        finally:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def _fetch_header(
        self,
        connection: ImapConnection,
        message_id: bytes,
        account: MailAccount,
    ) -> MailItem:
        status, data = connection.fetch(
            message_id,
            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
        )
        if status != "OK":
            raise ValueError("메일 헤더 조회 실패")
        header_bytes = next(
            (
                part[1]
                for part in data
                if isinstance(part, tuple) and isinstance(part[1], bytes)
            ),
            None,
        )
        if header_bytes is None:
            raise ValueError("메일 헤더가 비어 있습니다")
        message = BytesParser(policy=policy.default).parsebytes(header_bytes)
        sender_header = decode_mime_header(message.get("From"))
        sender_name, sender_address = parseaddr(sender_header)
        sender = sender_name.strip() or sender_address.strip() or "발신자 없음"
        subject = decode_mime_header(message.get("Subject")) or "(제목 없음)"
        at = self._parse_date(message.get("Date"))
        return MailItem(
            account=account.name,
            sender=sender,
            subject=subject,
            at=at,
            mailbox_url=account.mailbox_url,
        )

    def _parse_date(self, value: str | None) -> datetime | None:
        if not value:
            self._date_parse_failures += 1
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            self._date_parse_failures += 1
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._timezone)
        return parsed.astimezone(self._timezone)
