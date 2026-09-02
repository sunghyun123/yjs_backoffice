import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.worklog_index import SQLiteWorkLogIndex


def make_index(path, *, synced_at: str = "2026-08-18T10:00:00+09:00") -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE work_log (
            indx INTEGER PRIMARY KEY,
            c_date TEXT NOT NULL,
            u_name TEXT NOT NULL,
            gubun TEXT NOT NULL,
            detail TEXT,
            hashfname TEXT NOT NULL
        );
        CREATE TABLE collaboration (
            hashfname TEXT PRIMARY KEY,
            title TEXT NOT NULL
        );
        CREATE TABLE sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    connection.executemany(
        "INSERT INTO work_log VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, f"{today} 08:00:00", "홍길동", "ADD", "첫 작업", "p1"),
            (2, f"{today} 09:00:00", "김영희", "EDIT", "수정 작업", "p1"),
            (3, f"{today} 09:30:00", "김영희", "Link_Open", "열람", "p2"),
        ],
    )
    connection.execute("INSERT INTO collaboration VALUES ('p1', '프로젝트 1')")
    connection.executemany(
        "INSERT INTO sync_state VALUES (?, ?)",
        [
            ("last_sync_at", synced_at),
            ("last_error", ""),
            ("row_count", "3"),
        ],
    )
    connection.commit()
    connection.close()


def test_shared_index_returns_last_touch_and_valid_recent_edits(tmp_path) -> None:
    path = tmp_path / "wiki_index.db"
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    make_index(path, synced_at=now.isoformat())
    index = SQLiteWorkLogIndex(path, ZoneInfo("Asia/Seoul"), max_age_seconds=600)

    touches = index.fetch_project_last_touches()
    edits = index.fetch_recent_edits()
    health = index.health()

    assert touches["p1"].hour == 9
    assert "p2" not in touches
    assert [item["gubun"] for item in edits] == ["EDIT", "ADD"]
    assert edits[0]["project"] == "프로젝트 1"
    assert health["healthy"] is True
    assert health["row_count"] == 3


def test_shared_index_reports_stale_sync(tmp_path) -> None:
    path = tmp_path / "wiki_index.db"
    make_index(path, synced_at="2020-01-01T00:00:00+09:00")
    index = SQLiteWorkLogIndex(path, ZoneInfo("Asia/Seoul"), max_age_seconds=600)

    assert index.health()["healthy"] is False


def test_shared_index_rejects_an_incompatible_schema(tmp_path) -> None:
    path = tmp_path / "wiki_index.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.commit()
    connection.close()
    index = SQLiteWorkLogIndex(path, ZoneInfo("Asia/Seoul"), max_age_seconds=600)

    with pytest.raises(ValueError, match="work_log"):
        index.health()
