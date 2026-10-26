import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain import StatusThresholds
from app.state_store import DashboardStateStore


def test_state_store_persists_marks_settings_and_restorable_backup(tmp_path) -> None:
    path = tmp_path / "dashboard.db"
    store = DashboardStateStore(path, ZoneInfo("Asia/Seoul"))
    thresholds = StatusThresholds(
        active_days=5,
        idle_days=10,
        dormant_days=20,
        online_minutes=30,
    )

    store.set_mark("project-1", "hold", "자재 대기")
    store.set_thresholds(thresholds)
    backup = store.backup_if_due()
    store.close()

    assert backup is not None
    assert backup.exists()
    with sqlite3.connect(backup) as restored:
        mark = restored.execute(
            "SELECT mark, memo FROM project_mark WHERE hashfname = 'project-1'"
        ).fetchone()
        settings = dict(restored.execute("SELECT k, v FROM setting").fetchall())
        setting_timestamps = restored.execute(
            "SELECT DISTINCT updated_at FROM setting"
        ).fetchall()
    assert mark == ("hold", "자재 대기")
    assert settings["online_minutes"] == "30"
    assert len(setting_timestamps) == 1
    assert setting_timestamps[0][0]

    reopened = DashboardStateStore(path, ZoneInfo("Asia/Seoul"))
    assert reopened.get_marks() == {"project-1": "hold"}
    assert reopened.get_thresholds() == thresholds
    reopened.delete_mark("project-1")
    assert reopened.get_marks() == {}
    reopened.close()


def test_daily_backup_is_not_rewritten_without_state_change(tmp_path) -> None:
    store = DashboardStateStore(tmp_path / "dashboard.db", ZoneInfo("Asia/Seoul"))
    backup = store.backup_if_due()
    assert backup is not None
    old_timestamp = 946684800
    os.utime(backup, (old_timestamp, old_timestamp))

    assert store.backup_if_due() == backup
    assert int(backup.stat().st_mtime) == old_timestamp

    store.set_mark("project-1", "done")
    with sqlite3.connect(backup) as restored:
        mark = restored.execute(
            "SELECT mark FROM project_mark WHERE hashfname = 'project-1'"
        ).fetchone()
    assert mark == ("done",)
    store.close()


def test_state_store_retains_exactly_thirty_calendar_days_of_backups(tmp_path) -> None:
    timezone = ZoneInfo("Asia/Seoul")
    today = datetime.now(timezone).date()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    expired = backup_dir / f"dashboard-{(today - timedelta(days=30)).isoformat()}.db"
    retained = backup_dir / f"dashboard-{(today - timedelta(days=29)).isoformat()}.db"
    expired.touch()
    retained.touch()

    store = DashboardStateStore(tmp_path / "dashboard.db", timezone)
    store.close()

    assert not expired.exists()
    assert retained.exists()


def test_state_store_migrates_legacy_setting_table(tmp_path) -> None:
    path = tmp_path / "dashboard.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE setting (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        connection.execute("INSERT INTO setting VALUES ('online_minutes', '20')")

    store = DashboardStateStore(path, ZoneInfo("Asia/Seoul"))
    try:
        columns = {
            row[1]
            for row in store._connection.execute(  # noqa: SLF001
                "PRAGMA table_info(setting)"
            ).fetchall()
        }
        assert "updated_at" in columns
        assert store.get_thresholds().online_minutes == 20
    finally:
        store.close()


def test_state_store_persists_shared_todos_and_deletes_completed_items(tmp_path) -> None:
    path = tmp_path / "dashboard.db"
    store = DashboardStateStore(path, ZoneInfo("Asia/Seoul"))
    first = store.add_todo("주간 보고 확인")
    second = store.add_todo("결재 문서 검토")
    store.close()

    reopened = DashboardStateStore(path, ZoneInfo("Asia/Seoul"))
    assert reopened.list_todos() == [first, second]
    assert reopened.delete_todo(first.id) is True
    assert reopened.delete_todo(first.id) is False
    assert reopened.list_todos() == [second]
    backup = reopened.backup_if_due()
    reopened.close()

    assert backup is not None
    with sqlite3.connect(backup) as restored:
        rows = restored.execute("SELECT id, text FROM todo_item ORDER BY id").fetchall()
    assert rows == [(second.id, "결재 문서 검토")]


def test_google_oauth_state_is_hashed_and_single_use(tmp_path) -> None:
    store = DashboardStateStore(tmp_path / "dashboard.db", ZoneInfo("Asia/Seoul"))
    state = store.create_google_oauth_state()

    row = store._connection.execute(  # noqa: SLF001
        "SELECT state_hash FROM google_oauth_state"
    ).fetchone()
    assert row is not None
    assert row[0] != state
    assert store.consume_google_oauth_state(state) is True
    assert store.consume_google_oauth_state(state) is False
    store.close()
