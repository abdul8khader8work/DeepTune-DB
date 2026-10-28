"""SQL guard: AST-only validation, no regex sanitising."""

import pytest

from src.services.sql_guard import SqlValidationError, validate_sql


def test_accepts_single_select() -> None:
    validated = validate_sql("SELECT id, email FROM public.users WHERE id = $1", 10_000)
    assert validated.sql.startswith("SELECT")
    assert validated.statement is not None


def test_accepts_trailing_semicolon_and_cte() -> None:
    validated = validate_sql(
        "WITH recent AS (SELECT * FROM orders WHERE created_at > now()) "
        "SELECT * FROM recent;",
        10_000,
    )
    assert validated.sql.endswith("recent")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE users SET email = 'x'",
        "DELETE FROM users",
        "DROP TABLE users",
        "CREATE TABLE t (id int)",
        "ALTER TABLE users ADD COLUMN x int",
        "TRUNCATE users",
        "INSERT INTO users (id) VALUES (1)",
        "SELECT 1; DROP TABLE users",
        "GRANT ALL ON users TO public",
    ],
)
def test_rejects_writes_and_multiple_statements(sql: str) -> None:
    with pytest.raises(SqlValidationError):
        validate_sql(sql, 10_000)


@pytest.mark.parametrize("sql", ["", "   ", "not sql at all"])
def test_rejects_empty_or_unparseable(sql: str) -> None:
    with pytest.raises(SqlValidationError):
        validate_sql(sql, 10_000)


def test_rejects_over_length_limit() -> None:
    with pytest.raises(SqlValidationError):
        validate_sql("SELECT " + "a" * 50, max_length=20)
