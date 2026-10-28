"""Symbolic engine: predicate extraction, pruning rules, and DDL emission."""

from __future__ import annotations

import pytest

from parsers.schema import ColumnStats, SchemaCatalog, TableStats
from search.symbolic import (
    SymbolicError,
    extract_predicates,
    generate_candidates,
)


def test_extracts_join_filter_and_ordering(join_sql: str, catalog: SchemaCatalog) -> None:
    predicates, tables = extract_predicates(join_sql, catalog)
    kinds = {(predicate.column.table.name, predicate.column.name, predicate.kind) for predicate in predicates}

    assert ("customers", "id", "join") in kinds
    assert ("orders", "customer_id", "join") in kinds
    assert ("orders", "channel", "equality") in kinds
    assert ("orders", "created_at", "range") in kinds
    assert {table.name for table in tables} == {"orders", "customers"}


def test_candidates_are_valid_and_reviewable(join_sql: str, catalog: SchemaCatalog) -> None:
    result = generate_candidates(join_sql, catalog)
    assert result.candidates
    for candidate in result.candidates:
        assert candidate.create_sql.startswith("CREATE INDEX CONCURRENTLY")
        assert "USING btree" in candidate.create_sql
        assert candidate.columns
        assert candidate.storage_bytes > 0
        assert candidate.write_impact_percentage > 0


def test_low_selectivity_and_boolean_columns_are_rejected(catalog: SchemaCatalog) -> None:
    sql = (
        "SELECT id FROM orders "
        "WHERE status = 'paid' AND is_paid = true AND customer_id = 7"
    )
    result = generate_candidates(sql, catalog)
    reasons = {rejection.description: rejection.reason for rejection in result.rejected}
    assert "distinct ratio below 5%" in reasons["public.orders.status"]
    assert "boolean columns" in reasons["public.orders.is_paid"]
    assert any(candidate.columns == ("customer_id",) for candidate in result.candidates)


def test_existing_index_is_not_duplicated(catalog: SchemaCatalog) -> None:
    result = generate_candidates(
        "SELECT id FROM customers WHERE email = 'a@b.c'", catalog
    )
    assert all(candidate.columns != ("email",) for candidate in result.candidates)
    assert any("already has an index" in rejection.reason for rejection in result.rejected)


def test_json_containment_uses_gin(catalog: SchemaCatalog) -> None:
    result = generate_candidates(
        "SELECT id FROM events WHERE payload @> '{\"kind\": \"click\"}'", catalog
    )
    gin = [candidate for candidate in result.candidates if candidate.method == "gin"]
    assert gin
    assert gin[0].columns == ("payload",)
    assert "USING gin" in gin[0].create_sql


def test_storage_budget_prunes_wide_indexes() -> None:
    tiny = SchemaCatalog(
        tables=(
            TableStats(
                name="tiny",
                row_count=1_000,
                total_bytes=1_000,
                columns=(
                    ColumnStats("id", "bigint", n_distinct=1_000),
                    ColumnStats("a", "bigint", n_distinct=900),
                    ColumnStats("b", "bigint", n_distinct=800),
                ),
            ),
        )
    )
    result = generate_candidates("SELECT id FROM tiny WHERE a = 1 AND b = 2", tiny)
    assert not result.candidates
    assert any("15%" in rejection.reason for rejection in result.rejected)


def test_write_heavy_tables_are_capped(catalog: SchemaCatalog) -> None:
    sql = (
        "SELECT id FROM events WHERE customer_id = 1 "
        "AND created_at > now() - interval '1 hour' "
        "AND user_agent = 'x' AND ip = '1.2.3.4'"
    )
    result = generate_candidates(sql, catalog, goal="read_performance")
    assert len([c for c in result.candidates if c.table.name == "events"]) <= 3


def test_goal_controls_composite_width(join_sql: str, catalog: SchemaCatalog) -> None:
    minimal = generate_candidates(join_sql, catalog, goal="minimal_storage")
    assert all(len(candidate.columns) == 1 for candidate in minimal.candidates)

    read = generate_candidates(join_sql, catalog, goal="read_performance")
    assert any(len(candidate.columns) > 1 for candidate in read.candidates)


def test_candidates_respect_left_prefix(join_sql: str, catalog: SchemaCatalog) -> None:
    result = generate_candidates(join_sql, catalog, goal="read_performance")
    by_table: dict[str, list[tuple[str, ...]]] = {}
    for candidate in result.candidates:
        by_table.setdefault(candidate.table.name, []).append(candidate.columns)
    for columns_list in by_table.values():
        widest = max(columns_list, key=len)
        for columns in columns_list:
            assert widest[: len(columns)] == columns


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders WHERE id = 1",
        "UPDATE orders SET status = 'x' WHERE id = 1",
        "INSERT INTO orders (id) VALUES (1)",
        "DROP TABLE orders",
        "SELECT 1; SELECT 2",
    ],
)
def test_non_read_only_statements_are_rejected(sql: str, catalog: SchemaCatalog) -> None:
    with pytest.raises(SymbolicError):
        generate_candidates(sql, catalog)


def test_unknown_goal_is_rejected(catalog: SchemaCatalog) -> None:
    with pytest.raises(SymbolicError):
        generate_candidates("SELECT id FROM orders WHERE customer_id = 1", catalog, goal="turbo")


def test_no_predicates_returns_empty_result(catalog: SchemaCatalog) -> None:
    result = generate_candidates("SELECT id FROM orders", catalog)
    assert result.candidates == ()
    assert result.rejected
