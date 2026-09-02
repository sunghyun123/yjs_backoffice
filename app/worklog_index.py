from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


Row = dict[str, Any]
VALID_CHANGE_TYPES = ("ADD", "EDIT", "DEL", "MOVE", "PASTE", "LINK")
REQUIRED_SCHEMA = {
    "work_log": {"indx", "c_date", "u_name", "gubun", "detail", "hashfname"},
    "collaboration": {"hashfname", "title"},
    "sync_state": {"key", "value"},
}


class SQLiteWorkLogIndex:
    """Read-only access to the rebuildable ThinkWise work-log index."""

    def __init__(self, path: Path, timezone: ZoneInfo, max_age_seconds: int) -> None:
        self._path = path
        self._timezone = timezone
        self._max_age_seconds = max_age_seconds
        self._schema_validated = False

    def _connect(self) -> sqlite3.Connection:
        if not self._path.is_file():
            raise FileNotFoundError("씽크와이즈 작업 이력 색인이 없습니다.")
        connection = sqlite3.connect(
            f"file:{self._path.as_posix()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        if not self._schema_validated:
            try:
                self._validate_schema(connection)
            except Exception:
                connection.close()
                raise
            self._schema_validated = True
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        for table, required_columns in REQUIRED_SCHEMA.items():
            rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            actual_columns = {str(row["name"]) for row in rows}
            missing = sorted(required_columns - actual_columns)
            if missing:
                raise ValueError(
                    f"공유 색인 스키마가 호환되지 않습니다: {table}.{','.join(missing)}"
                )

    def fetch_project_last_touches(self) -> dict[str, datetime]:
        placeholders = ", ".join("?" for _ in VALID_CHANGE_TYPES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT hashfname, MAX(c_date) AS last_touch
                  FROM work_log
                 WHERE hashfname <> ''
                   AND gubun IN ({placeholders})
                 GROUP BY hashfname
                """,
                VALID_CHANGE_TYPES,
            ).fetchall()
        return {
            str(row["hashfname"]): datetime.fromisoformat(str(row["last_touch"]))
            for row in rows
            if row["hashfname"] and row["last_touch"]
        }

    def fetch_recent_edits(self, limit: int = 30) -> list[Row]:
        safe_limit = max(1, min(limit, 100))
        today_start = datetime.now(self._timezone).date().isoformat()
        placeholders = ", ".join("?" for _ in VALID_CHANGE_TYPES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT w.c_date, w.u_name, w.gubun, w.detail,
                       c.title AS project
                  FROM work_log w
                  LEFT JOIN collaboration c ON c.hashfname = w.hashfname
                 WHERE w.c_date >= ?
                   AND w.gubun IN ({placeholders})
                   AND w.detail IS NOT NULL
                   AND w.detail <> ''
                 ORDER BY w.indx DESC
                 LIMIT ?
                """,
                (today_start, *VALID_CHANGE_TYPES, safe_limit),
            ).fetchall()
        result: list[Row] = []
        for row in rows:
            item = dict(row)
            item["c_date"] = datetime.fromisoformat(str(item["c_date"]))
            result.append(item)
        return result

    def health(self) -> dict[str, object]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, value
                  FROM sync_state
                 WHERE key IN ('last_sync_at', 'last_error', 'row_count')
                """
            ).fetchall()
        state = {str(row["key"]): str(row["value"]) for row in rows}
        last_sync_raw = state.get("last_sync_at", "")
        last_sync = datetime.fromisoformat(last_sync_raw) if last_sync_raw else None
        if last_sync is not None and last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=self._timezone)
        age_seconds = (
            max(0, int((datetime.now(self._timezone) - last_sync).total_seconds()))
            if last_sync is not None
            else None
        )
        error = state.get("last_error", "")
        healthy = (
            last_sync is not None
            and not error
            and age_seconds is not None
            and age_seconds <= self._max_age_seconds
        )
        return {
            "mode": "shared_sqlite_index",
            "healthy": healthy,
            "last_sync_at": last_sync.isoformat() if last_sync else None,
            "age_seconds": age_seconds,
            "row_count": int(state.get("row_count", "0") or 0),
            "has_error": bool(error),
        }

    def close(self) -> None:
        return None
