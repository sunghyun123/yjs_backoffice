from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.repository import ThinkWiseRepository


CHECKS: dict[str, tuple[str, tuple[Any, ...]]] = {
    "board_columns": (
        """
        SELECT COLUMN_NAME, DATA_TYPE
          FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = 'tw_colman'
           AND TABLE_NAME = 'collaboration_board'
           AND COLUMN_NAME IN ('UPD_DATE', 'REG_DATE', 'CRT_DATE', 'MEMBER_NAME')
         ORDER BY ORDINAL_POSITION
        """,
        (),
    ),
    "connection_duplicates": (
        """
        SELECT COUNT(*) AS recent_rows,
               COUNT(DISTINCT u_id) AS distinct_users
          FROM tw_colla_log.conn_usertime
         WHERE uptime >= NOW() - INTERVAL 15 MINUTE
        """,
        (),
    ),
    "work_log_primary_key": (
        """
        SELECT COLUMN_NAME, SEQ_IN_INDEX
          FROM information_schema.STATISTICS
         WHERE TABLE_SCHEMA = 'tw_colla_log'
           AND TABLE_NAME = 'work_log'
           AND INDEX_NAME = 'PRIMARY'
         ORDER BY SEQ_IN_INDEX
        """,
        (),
    ),
    "update_time_alignment": (
        """
        SELECT COUNT(*) AS checked_projects,
               SUM(
                   CASE
                     WHEN latest.work_at IS NOT NULL
                      AND ABS(TIMESTAMPDIFF(
                          SECOND,
                          COALESCE(b.UPD_DATE, b.REG_DATE, b.CRT_DATE),
                          latest.work_at
                      )) <= 300
                     THEN 1 ELSE 0
                   END
               ) AS within_five_minutes
          FROM tw_colman.collaboration_board b
          LEFT JOIN (
              SELECT hashfname, MAX(c_date) AS work_at
                FROM tw_colla_log.work_log
               GROUP BY hashfname
          ) latest ON latest.hashfname = b.HASHFNAME
         WHERE COALESCE(b.DEL_YN, 'N') <> 'Y'
        """,
        (),
    ),
    "owner_field_coverage": (
        """
        SELECT COUNT(*) AS total_projects,
               SUM(CASE WHEN MEMBER_NAME IS NOT NULL AND MEMBER_NAME <> '' THEN 1 ELSE 0 END)
                   AS named_projects
          FROM tw_colman.collaboration_board
         WHERE COALESCE(DEL_YN, 'N') <> 'Y'
        """,
        (),
    ),
}


def main() -> int:
    try:
        settings = Settings(app_demo_mode=False)
    except Exception as exc:
        print(f"설정 오류: {type(exc).__name__}", file=sys.stderr)
        print(".env에 읽기 전용 DB 접속 정보를 넣은 뒤 다시 실행하세요.", file=sys.stderr)
        return 2

    repository = ThinkWiseRepository(settings)
    results: dict[str, Any] = {}
    try:
        for name, (sql, params) in CHECKS.items():
            results[name] = repository._select(sql, params)  # Phase 0 전용 진단
    except Exception as exc:
        print(f"검증 실패: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        repository.close()

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print("\n주의: MEMBER_NAME의 업무상 의미는 결과와 실제 화면을 표본 대조해 사람이 확정해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
