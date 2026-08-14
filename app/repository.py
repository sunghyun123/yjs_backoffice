from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings


Row = dict[str, Any]


class DashboardRepository(Protocol):
    def fetch_projects(self) -> list[Row]: ...

    def fetch_online_users(self, online_minutes: int) -> list[Row]: ...

    def fetch_active_users_30d(self) -> int: ...

    def fetch_recent_edits(self, limit: int = 30) -> list[Row]: ...

    def close(self) -> None: ...


_LEADING_COMMENT = re.compile(r"\A(?:\s|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*", re.DOTALL)


def assert_read_only_sql(sql: str) -> None:
    """Reject any statement that is not a single SELECT query."""

    statement = _LEADING_COMMENT.sub("", sql).strip()
    if not statement.upper().startswith("SELECT"):
        raise ValueError("운영 DB에는 SELECT 문만 실행할 수 있습니다.")
    without_terminal = statement[:-1] if statement.endswith(";") else statement
    if ";" in without_terminal:
        raise ValueError("여러 SQL 문을 한 번에 실행할 수 없습니다.")


class ThinkWiseRepository:
    """Minimal, SELECT-only access to the ThinkWise MariaDB schemas."""

    PROJECTS_SQL = """
        SELECT b.SEQ, b.HASHFNAME, b.TITLE, b.MEMBER_NAME, b.TREE_CNT,
               COALESCE(b.UPD_DATE, b.REG_DATE, b.CRT_DATE) AS last_touch,
               DATEDIFF(NOW(), COALESCE(b.UPD_DATE, b.REG_DATE, b.CRT_DATE)) AS idle_days,
               (SELECT COUNT(*)
                  FROM tw_colman.collaboration_participant p
                 WHERE p.COL_IDX = b.SEQ) AS member_cnt
          FROM tw_colman.collaboration_board b
         WHERE COALESCE(b.DEL_YN, 'N') <> 'Y'
         ORDER BY last_touch DESC
    """

    ONLINE_USERS_SQL = """
        SELECT c.u_id, u.MEMBER_NAME, c.uptime, b.TITLE
          FROM tw_colla_log.conn_usertime c
          LEFT JOIN tw_colman.collaboration_user u ON u.MEMBER_ID = c.u_id
          LEFT JOIN tw_colman.collaboration_board b ON b.HASHFNAME = c.hashfname
         WHERE c.uptime >= NOW() - INTERVAL %s MINUTE
         ORDER BY c.uptime DESC
    """

    ACTIVE_USERS_SQL = """
        SELECT COUNT(DISTINCT u_id) AS active_users
          FROM tw_colla_log.conn_usertime
         WHERE uptime >= NOW() - INTERVAL 30 DAY
    """

    RECENT_EDITS_SQL = """
        SELECT w.c_date, w.u_name, w.gubun, w.detail, b.TITLE AS project
          FROM tw_colla_log.work_log w
          LEFT JOIN tw_colman.collaboration_board b ON b.HASHFNAME = w.hashfname
         WHERE w.c_date >= CURDATE()
           AND w.gubun IN ('ADD', 'EDIT', 'DEL', 'MOVE', 'PASTE', 'LINK')
           AND w.detail IS NOT NULL
           AND w.detail <> ''
         ORDER BY w.c_date DESC
         LIMIT %s
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: pymysql.Connection[DictCursor] | None = None
        self._lock = threading.Lock()

    def _connect(self) -> pymysql.Connection[DictCursor]:
        if self._connection is None:
            self._connection = pymysql.connect(
                host=self._settings.db_host,
                port=self._settings.db_port,
                user=self._settings.db_user,
                password=self._settings.db_password.get_secret_value(),
                charset=self._settings.db_charset,
                autocommit=True,
                connect_timeout=5,
                read_timeout=10,
                write_timeout=5,
                cursorclass=DictCursor,
            )
        else:
            self._connection.ping(reconnect=True)
        return self._connection

    def _select(self, sql: str, params: tuple[Any, ...] = ()) -> list[Row]:
        assert_read_only_sql(sql)
        with self._lock:
            connection = self._connect()
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def fetch_projects(self) -> list[Row]:
        return self._select(self.PROJECTS_SQL)

    def fetch_online_users(self, online_minutes: int) -> list[Row]:
        rows = self._select(self.ONLINE_USERS_SQL, (online_minutes,))
        latest_by_user: dict[str, Row] = {}
        for row in rows:
            user_id = str(row.get("u_id") or "")
            if user_id and user_id not in latest_by_user:
                latest_by_user[user_id] = row
        return list(latest_by_user.values())

    def fetch_active_users_30d(self) -> int:
        rows = self._select(self.ACTIVE_USERS_SQL)
        return int(rows[0].get("active_users") or 0) if rows else 0

    def fetch_recent_edits(self, limit: int = 30) -> list[Row]:
        safe_limit = max(1, min(limit, 100))
        return self._select(self.RECENT_EDITS_SQL, (safe_limit,))

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


def require_datetime(row: Mapping[str, Any], field: str) -> datetime:
    value = row.get(field)
    if not isinstance(value, datetime):
        raise ValueError(f"{field} 값이 datetime이 아닙니다.")
    return value
