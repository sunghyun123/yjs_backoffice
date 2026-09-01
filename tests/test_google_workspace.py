from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.google_workspace import GoogleWorkspaceCollector


def test_google_collector_reads_current_week_and_recent_personal_files() -> None:
    timezone = ZoneInfo("Asia/Seoul")
    now = datetime.now(timezone)
    monday = now.date() - timedelta(days=now.weekday())
    calls: list[str] = []

    def get_json(url: str, token: str) -> dict[str, object]:
        calls.append(url)
        assert token == "access-token"
        if "/calendar/" in url:
            return {
                "items": [
                    {
                        "id": "event-1",
                        "summary": "경영회의",
                        "status": "confirmed",
                        "start": {"dateTime": f"{monday.isoformat()}T10:00:00+09:00"},
                        "end": {"dateTime": f"{monday.isoformat()}T11:00:00+09:00"},
                    },
                    {
                        "id": "event-2",
                        "summary": "현장 방문",
                        "status": "confirmed",
                        "start": {"date": (monday + timedelta(days=2)).isoformat()},
                        "end": {"date": (monday + timedelta(days=3)).isoformat()},
                    },
                    {
                        "id": "cancelled",
                        "status": "cancelled",
                        "start": {"date": monday.isoformat()},
                    },
                ]
            }
        return {
            "files": [
                {
                    "id": "file/unsafe",
                    "name": "주간 현황.xlsx",
                    "mimeType": (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    "modifiedTime": now.isoformat(),
                }
            ]
        }

    collector = GoogleWorkspaceCollector(
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        timezone=timezone,
        refresh_interval_sec=300,
        configured=True,
        json_getter=get_json,
        token_provider=lambda: "access-token",
    )

    snapshot = collector.collect()

    assert snapshot.configured is True
    assert snapshot.authorized is True
    assert snapshot.week_start == monday
    assert snapshot.week_end == monday + timedelta(days=6)
    assert [event.title for event in snapshot.events] == ["경영회의", "현장 방문"]
    assert snapshot.events[1].all_day is True
    assert snapshot.files[0].kind == "spreadsheet"
    assert snapshot.files[0].open_url == "https://drive.google.com/open?id=file%2Funsafe"

    calendar_query = parse_qs(urlsplit(calls[0]).query)
    drive_query = parse_qs(urlsplit(calls[1]).query)
    assert calendar_query["singleEvents"] == ["true"]
    assert calendar_query["orderBy"] == ["startTime"]
    assert drive_query["corpora"] == ["user"]
    assert drive_query["orderBy"] == ["modifiedTime desc"]
    assert "mimeType !=" in drive_query["q"][0]


def test_google_collector_does_not_call_external_api_before_authorization() -> None:
    collector = GoogleWorkspaceCollector(
        client_id="client",
        client_secret="secret",
        refresh_token="",
        timezone=ZoneInfo("Asia/Seoul"),
        refresh_interval_sec=300,
        configured=True,
        json_getter=lambda _url, _token: (_ for _ in ()).throw(AssertionError()),
        token_provider=lambda: (_ for _ in ()).throw(AssertionError()),
    )

    snapshot = collector.collect()

    assert snapshot.configured is True
    assert snapshot.authorized is False
    assert snapshot.events == []
    assert snapshot.files == []
