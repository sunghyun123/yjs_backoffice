import imaplib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import MailSnapshot
from app.mail import MailAccount, MailCollector, decode_mime_header
from app.service import DashboardService, DemoRepository
from app.state_store import DashboardStateStore


class FakeImap:
    def __init__(self, *, fail: bool = False, date_header: str | None = None) -> None:
        self.fail = fail
        self.date_header = date_header or "Mon, 18 Aug 2026 09:30:00 +0900"
        self.readonly = None
        self.fetch_parts: list[str] = []

    def login(self, user: str, password: str):
        if self.fail:
            raise imaplib.IMAP4.error("login failed")
        return "OK", [b"logged in"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self.readonly = readonly
        return "OK", [b"2"]

    def search(self, charset, *criteria):
        return "OK", [b"1 2"]

    def fetch(self, message_set, message_parts):
        self.fetch_parts.append(message_parts)
        subject = "=?UTF-8?B?7YWM7Iqk7Yq4IOuplOydvA==?="
        header = (
            f"From: Example Sender <sender@example.test>\r\n"
            f"Subject: {subject}\r\n"
            f"Date: {self.date_header}\r\n\r\n"
        ).encode()
        return "OK", [(b"header", header), b")"]

    def logout(self):
        return "BYE", [b"logout"]


def test_mail_collector_preserves_unread_state_and_decodes_headers() -> None:
    fake = FakeImap()
    collector = MailCollector(
        [
            MailAccount(
                "daou",
                "imap.example.test",
                993,
                "user@example.test",
                "secret",
                "https://mail.example.test/",
            )
        ],
        ZoneInfo("Asia/Seoul"),
        300,
        imap_factory=lambda host, port, timeout: fake,
    )

    snapshot = collector.collect()

    assert fake.readonly is True
    assert all("BODY.PEEK" in parts for parts in fake.fetch_parts)
    assert snapshot.unread_total == 2
    assert snapshot.unread_by_account == {"daou": 2}
    assert snapshot.items[0].subject == "테스트 메일"
    assert snapshot.items[0].sender == "Example Sender"
    assert snapshot.items[0].at == datetime(2026, 8, 18, 9, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    assert snapshot.stale is False


def test_mail_collector_keeps_other_accounts_when_one_fails() -> None:
    calls = 0

    def factory(host: str, port: int, timeout: int):
        nonlocal calls
        calls += 1
        return FakeImap(fail=calls == 1)

    collector = MailCollector(
        [
            MailAccount("daou", "a", 993, "u", "p", "#"),
            MailAccount("gmail", "b", 993, "u", "p", "#"),
        ],
        ZoneInfo("Asia/Seoul"),
        300,
        imap_factory=factory,
    )

    snapshot = collector.collect()

    assert snapshot.stale is True
    assert snapshot.error == "1개 메일 계정 갱신 실패"
    assert snapshot.unread_by_account == {"daou": 0, "gmail": 2}
    assert len(snapshot.items) == 2


def test_decode_mime_header_handles_plain_and_empty_values() -> None:
    assert decode_mime_header("plain subject") == "plain subject"
    assert decode_mime_header(None) == ""


def test_mail_collector_records_date_parse_failure_without_personal_data(
    caplog,
) -> None:
    fake = FakeImap(date_header="not-a-date")
    collector = MailCollector(
        [MailAccount("daou", "host", 993, "user", "password", "https://mail.test/")],
        ZoneInfo("Asia/Seoul"),
        300,
        imap_factory=lambda host, port, timeout: fake,
    )

    with caplog.at_level(logging.WARNING, logger="app.mail"):
        snapshot = collector.collect()

    assert all(item.at is None for item in snapshot.items)
    assert "메일 날짜 헤더 2건" in caplog.text
    assert "Example Sender" not in caplog.text
    assert "테스트 메일" not in caplog.text


def test_dashboard_service_uses_mail_collector_in_real_data_mode() -> None:
    settings = Settings(
        _env_file=None,
        app_demo_mode=False,
        db_user="readonly",
        db_password="secret",
        sqlite_path=":memory:",
    )
    store = DashboardStateStore(settings.resolved_sqlite_path, settings.timezone)

    class StubCollector:
        def collect(self) -> MailSnapshot:
            return MailSnapshot(unread_total=3, unread_by_account={"daou": 3})

    service = DashboardService(
        DemoRepository(settings),
        settings,
        store,
        StubCollector(),  # type: ignore[arg-type]
    )

    try:
        assert service.load_mail().unread_total == 3
    finally:
        service.close()
