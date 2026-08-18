from datetime import datetime, timedelta

import pytest

from app.config import Settings
from app.repository import ThinkWiseRepository, assert_read_only_sql


class WorkLogIndexStub:
    def __init__(self, last_touches: dict[str, datetime]) -> None:
        self.last_touches = last_touches

    def fetch_project_last_touches(self) -> dict[str, datetime]:
        return self.last_touches

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "\n -- dashboard query\n SELECT * FROM table_name",
        "/* safe diagnostic */ SELECT COUNT(*) FROM information_schema.COLUMNS;",
    ],
)
def test_read_only_guard_accepts_select(sql: str) -> None:
    assert_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE table_name SET x = 1",
        "DELETE FROM table_name",
        "INSERT INTO table_name VALUES (1)",
        "CREATE TABLE x (id INT)",
        "SELECT 1; DELETE FROM table_name",
    ],
)
def test_read_only_guard_rejects_mutation_or_multiple_statements(sql: str) -> None:
    with pytest.raises(ValueError):
        assert_read_only_sql(sql)


def test_projects_are_resorted_by_shared_index_last_touch(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    now = datetime.now(settings.timezone)
    index = WorkLogIndexStub(
        {
            "older-in-board": now,
            "newer-in-board": now - timedelta(days=3),
        }
    )
    repository = ThinkWiseRepository(settings, index)  # type: ignore[arg-type]
    board_rows = [
        {
            "HASHFNAME": "newer-in-board",
            "last_touch": now,
            "idle_days": 0,
        },
        {
            "HASHFNAME": "older-in-board",
            "last_touch": now - timedelta(days=100),
            "idle_days": 100,
        },
    ]
    monkeypatch.setattr(repository, "_select", lambda *_args, **_kwargs: board_rows)

    rows = repository.fetch_projects()

    assert [row["HASHFNAME"] for row in rows] == [
        "older-in-board",
        "newer-in-board",
    ]
    assert rows[0]["idle_days"] == 0
    assert rows[1]["idle_days"] == 3
