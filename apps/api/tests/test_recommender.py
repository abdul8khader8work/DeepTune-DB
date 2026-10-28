"""Heuristic candidate generation from the sqlglot AST."""

from src.schemas.connections import ColumnSchema, TableSchema
from src.services.recommender import recommend_indexes
from src.services.sql_guard import validate_sql

SQL = """
SELECT o.id, u.email
FROM public.orders AS o
JOIN public.users AS u ON u.id = o.user_id
WHERE o.status = 'paid' AND o.created_at > now() - interval '1 day'
ORDER BY o.created_at DESC
"""


def _table(name: str, columns: list[str], rows: int) -> TableSchema:
    return TableSchema(
        name=name,
        schema_name="public",
        row_estimate=rows,
        columns=[
            ColumnSchema(
                name=column,
                data_type="text",
                is_nullable=True,
                is_primary_key=False,
                existing_indexes=[],
            )
            for column in columns
        ],
    )


TABLES = [
    _table("orders", ["id", "user_id", "status", "created_at"], 250_000),
    _table("users", ["id", "email"], 10_000),
]


def test_recommends_concurrent_indexes() -> None:
    validated = validate_sql(SQL, 10_000)
    recommendations = recommend_indexes(validated, TABLES, "balanced")

    assert recommendations
    for item in recommendations:
        assert item.sql_statement.startswith("CREATE INDEX CONCURRENTLY ")
        assert item.target_columns
        assert item.target_table in {"orders", "users"}
        assert item.validated_speedup_factor is None
        assert 0 < item.confidence_score <= 1


def test_minimal_storage_returns_one_candidate() -> None:
    validated = validate_sql(SQL, 10_000)
    recommendations = recommend_indexes(validated, TABLES, "minimal_storage")
    assert len(recommendations) == 1


def test_unknown_table_is_ignored() -> None:
    validated = validate_sql("SELECT * FROM missing WHERE id = 1", 10_000)
    assert recommend_indexes(validated, TABLES, "balanced") == []
