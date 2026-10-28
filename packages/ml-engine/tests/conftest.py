"""Shared fixtures: a compact catalog and EXPLAIN payloads."""

from __future__ import annotations

from typing import Any

import pytest

from parsers.schema import ColumnStats, SchemaCatalog, TableStats


@pytest.fixture()
def catalog() -> SchemaCatalog:
    return SchemaCatalog(
        tables=(
            TableStats(
                name="customers",
                row_count=10_000,
                columns=(
                    ColumnStats("id", "bigint", is_primary_key=True, n_distinct=10_000),
                    ColumnStats(
                        "email",
                        "text",
                        n_distinct=10_000,
                        existing_indexes=("customers_email_key",),
                    ),
                    ColumnStats("country", "text", n_distinct=5),
                    ColumnStats("is_active", "boolean", n_distinct=2),
                    ColumnStats("created_at", "timestamptz", n_distinct=9_000),
                    ColumnStats("notes", "text", n_distinct=8_000),
                    ColumnStats("phone", "text", n_distinct=9_000),
                ),
            ),
            TableStats(
                name="orders",
                row_count=50_000,
                columns=(
                    ColumnStats("id", "bigint", is_primary_key=True, n_distinct=50_000),
                    ColumnStats("customer_id", "bigint", n_distinct=10_000),
                    ColumnStats("status", "text", n_distinct=4),
                    ColumnStats("is_paid", "boolean", n_distinct=2),
                    ColumnStats("total_cents", "integer", n_distinct=20_000),
                    ColumnStats("created_at", "timestamptz", n_distinct=45_000),
                    ColumnStats("shipping_address", "text", n_distinct=40_000),
                    ColumnStats("channel", "text", n_distinct=8),
                    ColumnStats("currency", "char(3)", n_distinct=4),
                ),
            ),
            TableStats(
                name="events",
                row_count=100_000,
                is_write_heavy=True,
                columns=(
                    ColumnStats("id", "bigint", is_primary_key=True, n_distinct=100_000),
                    ColumnStats("customer_id", "bigint", n_distinct=10_000),
                    ColumnStats("payload", "jsonb", n_distinct=90_000),
                    ColumnStats("kind", "text", n_distinct=10),
                    ColumnStats("created_at", "timestamptz", n_distinct=95_000),
                    ColumnStats("source", "text", n_distinct=15),
                    ColumnStats("user_agent", "text", n_distinct=60_000),
                    ColumnStats("ip", "text", n_distinct=70_000),
                ),
            ),
        )
    )


@pytest.fixture()
def explain_payload() -> dict[str, Any]:
    return {
        "Plan": {
            "Node Type": "Limit",
            "Plan Rows": 10,
            "Actual Rows": 10,
            "Total Cost": 420.5,
            "Plan Width": 64,
            "Actual Total Time": 12.5,
            "Plans": [
                {
                    "Node Type": "Sort",
                    "Plan Rows": 500,
                    "Actual Rows": 450,
                    "Total Cost": 400.0,
                    "Plan Width": 64,
                    "Actual Total Time": 11.0,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "orders",
                            "Schema": "public",
                            "Alias": "o",
                            "Plan Rows": 500,
                            "Actual Rows": 450,
                            "Total Cost": 300.0,
                            "Plan Width": 64,
                            "Actual Total Time": 10.0,
                            "Filter": "(status = 'paid')",
                        }
                    ],
                }
            ],
        },
        "Planning Time": 0.4,
        "Execution Time": 12.5,
    }


@pytest.fixture()
def join_sql() -> str:
    return (
        "SELECT o.id, c.email FROM public.orders o "
        "JOIN public.customers c ON c.id = o.customer_id "
        "WHERE o.created_at > now() - interval '1 day' "
        "AND o.channel = 'web' "
        "ORDER BY o.created_at DESC"
    )
