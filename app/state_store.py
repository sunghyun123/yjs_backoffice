from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain import ManualStatus, StatusThresholds


class DashboardStateStore:
    """Durable dashboard-only state. It never writes to ThinkWise."""

    def __init__(self, path: Path, timezone: ZoneInfo) -> None:
        self._path = path
        self._timezone = timezone
        self._lock = threading.RLock()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(path),
            check_same_thread=False,
            timeout=5,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys=ON")
            if str(path) != ":memory:":
                self._connection.execute("PRAGMA journal_mode=WAL")
            self._initialize()
            self.backup_if_due()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_mark (
                hashfname  TEXT PRIMARY KEY,
                mark       TEXT NOT NULL CHECK(mark IN ('done', 'running', 'hold')),
                memo       TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS setting (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            );
            """
        )
        setting_columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(setting)").fetchall()
        }
        if "updated_at" not in setting_columns:
            self._connection.execute(
                "ALTER TABLE setting ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
            )
        self._connection.commit()

    def get_marks(self) -> dict[str, ManualStatus]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT hashfname, mark FROM project_mark"
            ).fetchall()
        return {str(row["hashfname"]): row["mark"] for row in rows}

    def set_mark(self, hashfname: str, mark: ManualStatus, memo: str = "") -> None:
        updated_at = datetime.now(self._timezone).isoformat(timespec="seconds")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO project_mark(hashfname, mark, memo, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(hashfname) DO UPDATE SET
                    mark = excluded.mark,
                    memo = excluded.memo,
                    updated_at = excluded.updated_at
                """,
                (hashfname, mark, memo, updated_at),
            )
            self._connection.commit()
            self.backup_if_due(force=True)

    def delete_mark(self, hashfname: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM project_mark WHERE hashfname = ?", (hashfname,)
            )
            self._connection.commit()
            self.backup_if_due(force=True)

    def get_thresholds(self) -> StatusThresholds:
        with self._lock:
            rows = self._connection.execute("SELECT k, v FROM setting").fetchall()
        values = {str(row["k"]): int(row["v"]) for row in rows}
        defaults = StatusThresholds()
        return StatusThresholds(
            active_days=values.get("active_days", defaults.active_days),
            idle_days=values.get("idle_days", defaults.idle_days),
            dormant_days=values.get("dormant_days", defaults.dormant_days),
            online_minutes=values.get("online_minutes", defaults.online_minutes),
        )

    def set_thresholds(self, thresholds: StatusThresholds) -> None:
        values = thresholds.model_dump()
        updated_at = datetime.now(self._timezone).isoformat(timespec="seconds")
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO setting(k, v, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(k) DO UPDATE SET
                    v = excluded.v,
                    updated_at = excluded.updated_at
                """,
                [(key, str(value), updated_at) for key, value in values.items()],
            )
            self._connection.commit()
            self.backup_if_due(force=True)

    def backup_if_due(self, *, force: bool = False) -> Path | None:
        if str(self._path) == ":memory:":
            return None
        with self._lock:
            backup_dir = (self._path.parent / "backups").resolve()
            backup_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(self._timezone).date()
            target = backup_dir / f"dashboard-{today.isoformat()}.db"
            self._remove_expired_backups(backup_dir, today)
            if target.exists() and not force:
                return target
            with sqlite3.connect(target) as destination:
                self._connection.backup(destination)
            return target

    def _remove_expired_backups(self, backup_dir: Path, today: date) -> None:
        cutoff = today - timedelta(days=29)
        for path in backup_dir.glob("dashboard-????-??-??.db"):
            try:
                backup_date = date.fromisoformat(path.stem.removeprefix("dashboard-"))
            except ValueError:
                continue
            if backup_date < cutoff and path.resolve().parent == backup_dir:
                path.unlink()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
