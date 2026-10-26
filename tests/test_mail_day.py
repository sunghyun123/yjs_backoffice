import imaplib
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import MailDayResult
from app.mail import MailAccount
from app.mail_day import (
    MailDayReader,
    MailFolder,
    choose_folders,
    decode_modified_utf7,
    imap_date,
    parse_internaldate,
    parse_list_line,
)
from app.main import create_app


KST = ZoneInfo("Asia/Seoul")
INBOX = ("(\\HasNoChildren)", "INBOX")


def raw_message(
    subject: str,
    body: str,
    *,
    html: bool = False,
    sender: str = "Sender Name <sender@example.test>",
    message_id: str | None = None,
) -> bytes:
    content_type = "text/html" if html else "text/plain"
    message_id_line = f"Message-ID: {message_id}\r\n" if message_id else ""
    return (
        f"From: {sender}\r\n"
        f"Subject: {subject}\r\n"
        f"{message_id_line}"
        "Date: Sun, 25 Oct 2026 09:00:00 +0900\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n\r\n"
        f"{body}\r\n"
    ).encode()


class FakeDayImap:
    """폴더마다 (INTERNALDATE 문자열, 원문) 목록을 갖는 가짜 IMAP 서버. UID = 폴더 안 순번 + 100."""

    def __init__(
        self,
        folders: dict[tuple[str, str], list[tuple[str, bytes]]],
        *,
        fail_login: bool = False,
    ) -> None:
        self.folders = folders
        self.fail_login = fail_login
        self.selected: str | None = None
        self.readonly_flags: list[bool] = []
        self.selected_names: list[str] = []
        self.search_criteria: tuple = ()
        self.body_fetch_calls: list[bytes] = []
        self.fetch_parts: list[str] = []

    def _messages(self) -> list[tuple[str, bytes]]:
        for (_, name), messages in self.folders.items():
            if f'"{name}"' == self.selected:
                return messages
        raise imaplib.IMAP4.error("no such folder")

    def login(self, user: str, password: str):
        if self.fail_login:
            raise imaplib.IMAP4.error("login failed")
        return "OK", [b"ok"]

    def list(self, directory: str = '""', pattern: str = "*"):
        return "OK", [f'{flags} "/" "{name}"'.encode() for flags, name in self.folders]

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self.selected = mailbox
        self.selected_names.append(mailbox)
        self.readonly_flags.append(readonly)
        return "OK", [str(len(self._messages())).encode()]

    def uid(self, command: str, *args):
        messages = self._messages()
        if command == "SEARCH":
            self.search_criteria = args[1:]
            return "OK", [" ".join(str(100 + index) for index in range(len(messages))).encode()]
        uid_set, parts = args
        self.fetch_parts.append(parts)
        uids = [int(uid) for uid in uid_set.split(b",")]
        if parts == "(INTERNALDATE)":
            return "OK", [
                f'{uid - 99} (UID {uid} INTERNALDATE "{messages[uid - 100][0]}")'.encode()
                for uid in uids
            ]
        self.body_fetch_calls.append(uid_set)
        data: list = []
        for uid in uids:
            raw = messages[uid - 100][1]
            data.append((f"{uid - 99} (UID {uid} BODY[]<0> {{{len(raw)}}}".encode(), raw))
            data.append(b")")
        return "OK", data

    def logout(self):
        return "BYE", [b"bye"]


def make_reader(fakes: dict[str, FakeDayImap], **kwargs) -> MailDayReader:
    accounts = [
        MailAccount(name, name, 993, "me@example.test", "p", "https://mail.test/")
        for name in fakes
    ]
    return MailDayReader(
        accounts,  # type: ignore[arg-type]
        KST,
        imap_factory=lambda host, port, timeout: fakes[host],
        **kwargs,
    )


def test_day_window_is_cut_by_kst_not_by_mail_server_date() -> None:
    # 메일 서버가 UTC(+0000)로 시각을 주는 경우. KST 10/25 하루 = UTC 10/24 15:00 ~ 10/25 15:00.
    fake = FakeDayImap(
        {
            INBOX: [
                ("24-Oct-2026 14:59:59 +0000", raw_message("before", "x")),  # KST 10/24 23:59:59
                ("24-Oct-2026 15:00:00 +0000", raw_message("first", "x")),  # KST 10/25 00:00:00
                ("25-Oct-2026 14:59:59 +0000", raw_message("last", "x")),  # KST 10/25 23:59:59
                ("25-Oct-2026 15:00:00 +0000", raw_message("after", "x")),  # KST 10/26 00:00:00
            ]
        }
    )
    result = make_reader({"gmail": fake}).read_day(date(2026, 10, 25))

    assert [message.subject for message in result.messages] == ["first", "last"]
    assert result.messages[0].received_at == datetime(2026, 10, 25, 0, 0, tzinfo=KST)
    assert result.window_start == datetime(2026, 10, 25, tzinfo=KST)
    assert result.window_end == datetime(2026, 10, 26, tzinfo=KST)
    # 서버 날짜 경계로 놓치지 않도록 앞뒤 하루씩 넓혀 검색한다.
    assert fake.search_criteria == ("SINCE", "24-Oct-2026", "BEFORE", "27-Oct-2026")


def test_day_read_never_marks_mail_as_read() -> None:
    fake = FakeDayImap({INBOX: [("25-Oct-2026 09:00:00 +0900", raw_message("s", "body"))]})
    make_reader({"daou": fake}).read_day(date(2026, 10, 25))

    assert fake.readonly_flags and all(fake.readonly_flags)
    body_fetches = [parts for parts in fake.fetch_parts if parts != "(INTERNALDATE)"]
    assert body_fetches and all("BODY.PEEK" in parts for parts in body_fetches)


def test_failed_account_is_reported_not_silently_empty() -> None:
    fakes = {
        "daou": FakeDayImap({INBOX: [("25-Oct-2026 09:00:00 +0900", raw_message("ok", "x"))]}),
        "naver": FakeDayImap({}, fail_login=True),
    }
    result = make_reader(fakes).read_day(date(2026, 10, 25))

    statuses = {status.account: status for status in result.accounts}
    assert statuses["daou"].ok is True and statuses["daou"].count == 1
    assert statuses["naver"].ok is False
    assert [message.account for message in result.messages] == ["daou"]


def test_unreadable_internaldate_fails_the_account() -> None:
    fake = FakeDayImap({INBOX: [("garbage", raw_message("s", "x"))]})
    result = make_reader({"daou": fake}).read_day(date(2026, 10, 25))

    assert result.accounts[0].ok is False
    assert result.messages == []


def test_over_limit_keeps_latest_and_flags_truncation() -> None:
    fake = FakeDayImap(
        {
            INBOX: [
                (f"25-Oct-2026 0{hour}:00:00 +0900", raw_message(f"m{hour}", "x"))
                for hour in range(1, 5)
            ]
        }
    )
    result = make_reader({"daou": fake}, max_messages_per_account=2).read_day(date(2026, 10, 25))

    assert result.accounts[0].truncated is True
    assert result.accounts[0].count == 2
    assert [message.subject for message in result.messages] == ["m3", "m4"]


def test_bodies_are_fetched_in_batches_not_one_by_one() -> None:
    fake = FakeDayImap(
        {
            INBOX: [
                (f"25-Oct-2026 {hour:02d}:00:00 +0900", raw_message(f"m{hour}", "x"))
                for hour in range(5)
            ]
        }
    )
    result = make_reader({"daou": fake}, fetch_batch_size=2).read_day(date(2026, 10, 25))

    assert len(result.messages) == 5
    assert fake.body_fetch_calls == [b"100,101", b"102,103", b"104"]


def test_non_gmail_reads_all_folders_except_sent_drafts_trash() -> None:
    fake = FakeDayImap(
        {
            INBOX: [("25-Oct-2026 09:00:00 +0900", raw_message("inbox", "x"))],
            # 네이버식 한글 폴더 이름(modified UTF-7). '거래처' 폴더는 읽고 '보낸메일함'은 건너뛴다.
            ("(\\HasNoChildren)", "&rHC3mMyY-"): [
                ("25-Oct-2026 10:00:00 +0900", raw_message("client", "x"))
            ],
            ("(\\HasNoChildren)", "&vPSwuLpUx3zVaA-"): [
                ("25-Oct-2026 11:00:00 +0900", raw_message("sent", "x"))
            ],
            ("(\\HasNoChildren \\Trash)", "Trash"): [
                ("25-Oct-2026 12:00:00 +0900", raw_message("trash", "x"))
            ],
        }
    )
    result = make_reader({"naver": fake}).read_day(date(2026, 10, 25))

    assert [(message.subject, message.folder) for message in result.messages] == [
        ("inbox", "INBOX"),
        ("client", "거래처"),
    ]


def test_gmail_reads_all_mail_and_spam_once_and_drops_own_sent_mail() -> None:
    fake = FakeDayImap(
        {
            INBOX: [("25-Oct-2026 09:00:00 +0900", raw_message("dup", "x", message_id="<a@x>"))],
            ("(\\HasNoChildren \\All)", "[Gmail]/All Mail"): [
                ("25-Oct-2026 09:00:00 +0900", raw_message("archived", "x", message_id="<a@x>")),
                (
                    "25-Oct-2026 10:00:00 +0900",
                    raw_message("mine", "x", sender="Me <ME@example.test>"),
                ),
            ],
            ("(\\HasNoChildren \\Junk)", "[Gmail]/Spam"): [
                ("25-Oct-2026 11:00:00 +0900", raw_message("spam", "x"))
            ],
        }
    )
    result = make_reader({"gmail": fake}).read_day(date(2026, 10, 25))

    assert [(message.subject, message.folder) for message in result.messages] == [
        ("archived", "[Gmail]/All Mail"),
        ("spam", "[Gmail]/Spam"),
    ]
    assert '"INBOX"' not in fake.selected_names


def test_html_body_is_converted_and_long_body_is_cut() -> None:
    html_body = "<html><style>p{}</style><p>안녕하세요&nbsp;대표님</p><p>견적 첨부</p></html>"
    fake = FakeDayImap(
        {
            INBOX: [
                ("25-Oct-2026 09:00:00 +0900", raw_message("html", html_body, html=True)),
                ("25-Oct-2026 10:00:00 +0900", raw_message("long", "가" * 50)),
            ]
        }
    )
    result = make_reader({"daou": fake}, body_chars=10).read_day(date(2026, 10, 25))

    html_message, long_message = result.messages
    assert "<" not in html_message.body and "p{}" not in html_message.body
    assert html_message.body.startswith("안녕하세요")
    assert html_message.sender == "Sender Name"
    assert html_message.sender_address == "sender@example.test"
    assert long_message.body == "가" * 10
    assert long_message.body_truncated is True


def test_internaldate_parser_handles_padding_and_offsets() -> None:
    parsed = parse_internaldate(b'1 (UID 9 INTERNALDATE " 5-Oct-2026 23:30:00 -0700")')
    assert parsed == datetime(2026, 10, 5, 23, 30, tzinfo=timezone(-timedelta(hours=7)))
    assert parse_internaldate(b"1 (FLAGS ())") is None
    assert imap_date(date(2026, 3, 7)) == "07-Mar-2026"


def test_folder_list_parsing_and_selection() -> None:
    assert decode_modified_utf7("&rHC3mMyY-") == "거래처"
    assert decode_modified_utf7("A&-B") == "A&B"
    literal = parse_list_line((b'(\\HasNoChildren) "/" {6}', b"Orders"))
    assert literal == MailFolder("Orders", "Orders", frozenset({"\\hasnochildren"}))
    noselect = MailFolder("[Gmail]", "[Gmail]", frozenset({"\\noselect"}))
    inbox = MailFolder("INBOX", "INBOX", frozenset())
    assert choose_folders([noselect, inbox]) == ([inbox], False)


def test_mail_day_api_uses_kst_today_and_validates_range() -> None:
    requested: list[date] = []

    class StubReader:
        def read_day(self, day: date) -> MailDayResult:
            requested.append(day)
            start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
            return MailDayResult(
                date=day,
                timezone="Asia/Seoul",
                window_start=start,
                window_end=start + timedelta(days=1),
                fetched_at=start,
            )

    settings = Settings(_env_file=None, app_demo_mode=True, sqlite_path=":memory:")
    app = create_app(settings, mail_day_reader=StubReader())  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get("/api/mail/day", params={"days_ago": 1})
        too_far = client.get("/api/mail/day", params={"days_ago": 31})

    assert response.status_code == 200
    assert requested == [datetime.now(KST).date() - timedelta(days=1)]
    assert response.json()["timezone"] == "Asia/Seoul"
    assert too_far.status_code == 422
