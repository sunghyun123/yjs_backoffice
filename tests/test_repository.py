import pytest

from app.repository import assert_read_only_sql


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
