"""Synthetic EXPLAIN workload generator with curriculum tiers.

Real TPC-H/TPC-DS collection requires a live PostgreSQL instance; Phase 3 ships
a deterministic generator so training, tests, and demos are reproducible
offline. Phase 4 can feed real ``EXPLAIN (ANALYZE, FORMAT JSON)`` payloads into
the same parser.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from parsers.schema import ColumnStats, SchemaCatalog, TableStats


@dataclass(frozen=True)
class WorkloadSample:
    query_id: str
    tier: int
    plan: dict[str, Any]
    execution_time_ms: float


@dataclass(frozen=True)
class SyntheticWorkload:
    catalog: SchemaCatalog
    samples: tuple[WorkloadSample, ...] = field(default_factory=tuple)
    tier: int = 0

    def __len__(self) -> int:
        return len(self.samples)


def build_demo_catalog() -> SchemaCatalog:
    """A small TPC-H-like schema with realistic cardinalities."""
    tables = (
        TableStats(
            name="customers",
            row_count=20_000,
            columns=(
                ColumnStats("id", "bigint", is_primary_key=True, n_distinct=20_000),
                ColumnStats("email", "text", n_distinct=20_000),
                ColumnStats("country", "text", n_distinct=5),
                ColumnStats("created_at", "timestamptz", n_distinct=18_000),
                ColumnStats("phone", "text", n_distinct=19_000),
                ColumnStats("address", "text", n_distinct=18_500),
                ColumnStats("notes", "text", n_distinct=12_000),
            ),
        ),
        TableStats(
            name="products",
            row_count=5_000,
            columns=(
                ColumnStats("id", "bigint", is_primary_key=True, n_distinct=5_000),
                ColumnStats("sku", "text", n_distinct=5_000),
                ColumnStats("name", "text", n_distinct=4_800),
                ColumnStats("category", "text", n_distinct=4),
                ColumnStats("price_cents", "integer", n_distinct=2_500),
                ColumnStats("brand", "text", n_distinct=300),
                ColumnStats("description", "text", n_distinct=4_500),
            ),
        ),
        TableStats(
            name="orders",
            row_count=120_000,
            columns=(
                ColumnStats("id", "bigint", is_primary_key=True, n_distinct=120_000),
                ColumnStats("customer_id", "bigint", n_distinct=20_000),
                ColumnStats("status", "text", n_distinct=4),
                ColumnStats("total_cents", "integer", n_distinct=40_000),
                ColumnStats("created_at", "timestamptz", n_distinct=110_000),
                ColumnStats("shipping_address", "text", n_distinct=100_000),
                ColumnStats("notes", "text", n_distinct=60_000),
                ColumnStats("currency", "char(3)", n_distinct=6),
                ColumnStats("channel", "text", n_distinct=8),
            ),
        ),
        TableStats(
            name="order_items",
            row_count=300_000,
            columns=(
                ColumnStats("id", "bigint", is_primary_key=True, n_distinct=300_000),
                ColumnStats("order_id", "bigint", n_distinct=120_000),
                ColumnStats("product_id", "bigint", n_distinct=5_000),
                ColumnStats("quantity", "integer", n_distinct=4),
                ColumnStats("unit_cents", "integer", n_distinct=20_000),
                ColumnStats("discount_cents", "integer", n_distinct=1_500),
                ColumnStats("tax_cents", "integer", n_distinct=2_000),
                ColumnStats("description", "text", n_distinct=250_000),
            ),
        ),
        TableStats(
            name="events",
            row_count=500_000,
            is_write_heavy=True,
            columns=(
                ColumnStats("id", "bigint", is_primary_key=True, n_distinct=500_000),
                ColumnStats("customer_id", "bigint", n_distinct=20_000),
                ColumnStats("kind", "text", n_distinct=12),
                ColumnStats("payload", "jsonb", n_distinct=400_000),
                ColumnStats("created_at", "timestamptz", n_distinct=450_000),
                ColumnStats("source", "text", n_distinct=20),
                ColumnStats("user_agent", "text", n_distinct=150_000),
                ColumnStats("ip", "text", n_distinct=300_000),
            ),
        ),
    )
    return SchemaCatalog(tables=tables)


def _table(catalog: SchemaCatalog, name: str) -> TableStats:
    table = catalog.find(name)
    if table is None:  # pragma: no cover - catalog is fixed
        raise KeyError(name)
    return table


def _scan(
    table: TableStats,
    rng: random.Random,
    selectivity: float,
    use_index: bool = False,
) -> dict[str, Any]:
    estimated = max(1, int(table.row_count * selectivity))
    actual = max(1, int(estimated * rng.uniform(0.7, 1.4)))
    width = table.avg_row_bytes
    node_type = "Index Scan" if use_index else "Seq Scan"
    unit_cost = 0.008 if use_index else 0.02
    cost = table.row_count * unit_cost * (1.0 + rng.random())
    node: dict[str, Any] = {
        "Node Type": node_type,
        "Relation Name": table.name,
        "Schema": table.schema_name,
        "Alias": f"{table.name[0]}{rng.randint(1, 9)}",
        "Plan Rows": estimated,
        "Actual Rows": actual,
        "Total Cost": round(cost, 2),
        "Plan Width": width,
        "Actual Total Time": round(cost * 0.03, 3),
        "Actual Loops": 1,
    }
    if selectivity < 1.0:
        node["Filter"] = f"({table.name}.{table.columns[0].name} predicate)"
        node["Rows Removed by Filter"] = max(0, table.row_count - actual)
    return node


def _join(kind: str, left: dict[str, Any], right: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    left_rows = int(left.get("Actual Rows", 1))
    right_rows = int(right.get("Actual Rows", 1))
    rows = max(1, int(min(left_rows, right_rows) * rng.uniform(0.05, 0.6)))
    cost = float(left["Total Cost"]) + float(right["Total Cost"]) + rows * rng.uniform(0.01, 0.05)
    return {
        "Node Type": kind,
        "Join Type": "Inner",
        "Plan Rows": max(1, int(rows * rng.uniform(0.8, 1.2))),
        "Actual Rows": rows,
        "Total Cost": round(cost, 2),
        "Plan Width": int(left.get("Plan Width", 16)) + int(right.get("Plan Width", 16)),
        "Actual Total Time": round(cost * 0.04, 3),
        "Actual Loops": 1,
        "Plans": [left, right],
    }


def _sort(child: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    rows = int(child.get("Actual Rows", 1))
    cost = float(child["Total Cost"]) + rows * math.log2(max(rows, 2)) * 0.002
    return {
        "Node Type": "Sort",
        "Plan Rows": int(child.get("Plan Rows", rows)),
        "Actual Rows": rows,
        "Total Cost": round(cost, 2),
        "Plan Width": int(child.get("Plan Width", 16)),
        "Actual Total Time": round(cost * 0.03, 3),
        "Actual Loops": 1,
        "Sort Key": ["created_at DESC"],
        "Plans": [child],
    }


def _limit(child: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    rows = min(int(child.get("Actual Rows", 1)), rng.choice((10, 25, 50, 100)))
    cost = float(child["Total Cost"]) + rows * 0.001
    return {
        "Node Type": "Limit",
        "Plan Rows": rows,
        "Actual Rows": rows,
        "Total Cost": round(cost, 2),
        "Plan Width": int(child.get("Plan Width", 16)),
        "Actual Total Time": round(cost * 0.02, 3),
        "Actual Loops": 1,
        "Plans": [child],
    }


def _aggregate(child: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    rows = max(1, int(int(child.get("Actual Rows", 1)) * rng.uniform(0.01, 0.2)))
    cost = float(child["Total Cost"]) + rows * 0.01
    return {
        "Node Type": rng.choice(("HashAggregate", "GroupAggregate")),
        "Plan Rows": rows,
        "Actual Rows": rows,
        "Total Cost": round(cost, 2),
        "Plan Width": 16,
        "Actual Total Time": round(cost * 0.05, 3),
        "Actual Loops": 1,
        "Group Key": ["category"],
        "Plans": [child],
    }


def _label_ms(root: dict[str, Any], rng: random.Random) -> float:
    cost = float(root["Total Cost"])
    rows = float(root.get("Actual Rows", 1))
    milliseconds = 0.08 + cost * 0.06 + math.log1p(rows) * 0.4
    # Synthetic EXPLAIN labels are near-deterministic: the generator is a
    # stand-in for ANALYZE timings, and heavy multiplicative noise would put a
    # ceiling on achievable rank correlation that has nothing to do with the
    # model. Phase 4 replaces these labels with real measurements.
    milliseconds *= rng.lognormvariate(0.0, 0.08)
    return round(max(0.05, milliseconds), 3)


def _wrap_payload(root: dict[str, Any], rng: random.Random) -> tuple[dict[str, Any], float]:
    milliseconds = _label_ms(root, rng)
    payload = {
        "Plan": root,
        "Planning Time": round(rng.uniform(0.05, 2.0), 3),
        "Execution Time": milliseconds,
    }
    return payload, milliseconds


def _tier_one(catalog: SchemaCatalog, rng: random.Random) -> dict[str, Any]:
    table = _table(catalog, rng.choice(("customers", "products", "orders")))
    scan = _scan(table, rng, selectivity=rng.uniform(0.01, 0.4))
    if rng.random() < 0.5:
        return _limit(_sort(scan, rng), rng)
    return _aggregate(scan, rng)


def _tier_two(catalog: SchemaCatalog, rng: random.Random) -> dict[str, Any]:
    pairs = (
        ("orders", "customers"),
        ("order_items", "orders"),
        ("order_items", "products"),
    )
    left_name, right_name = rng.choice(pairs)
    left = _scan(_table(catalog, left_name), rng, rng.uniform(0.005, 0.2))
    right = _scan(_table(catalog, right_name), rng, rng.uniform(0.01, 0.3))
    joined = _join(
        rng.choice(("Hash Join", "Nested Loop", "Merge Join")), left, right, rng
    )
    if rng.random() < 0.4:
        joined = _sort(joined, rng)
    return _limit(joined, rng)


def _tier_three(catalog: SchemaCatalog, rng: random.Random) -> dict[str, Any]:
    chains = (
        ("order_items", "orders", "customers"),
        ("order_items", "orders", "customers", "products"),
        ("events", "customers", "orders"),
        ("order_items", "products", "orders", "customers", "events"),
    )
    chain = list(rng.choice(chains))
    rng.shuffle(chain)
    node = _scan(_table(catalog, chain[0]), rng, rng.uniform(0.002, 0.1))
    for name in chain[1:]:
        other = _scan(_table(catalog, name), rng, rng.uniform(0.005, 0.2))
        node = _join(
            rng.choice(("Hash Join", "Nested Loop", "Merge Join")), node, other, rng
        )
    if rng.random() < 0.5:
        node = _aggregate(node, rng)
    return _limit(_sort(node, rng), rng)


_BUILDERS = {1: _tier_one, 2: _tier_two, 3: _tier_three}


def generate_workload(
    tier: int,
    count: int,
    seed: int,
    catalog: SchemaCatalog | None = None,
) -> SyntheticWorkload:
    """Generate ``count`` labelled plans for a curriculum tier (1-3)."""
    if tier not in _BUILDERS:
        raise ValueError("tier must be 1, 2, or 3")
    if count < 0:
        raise ValueError("count must be non-negative")
    schema = catalog or build_demo_catalog()
    rng = random.Random(seed)
    samples: list[WorkloadSample] = []
    for index in range(count):
        root = _BUILDERS[tier](schema, rng)
        payload, milliseconds = _wrap_payload(root, rng)
        samples.append(
            WorkloadSample(
                query_id=f"t{tier}-{seed}-{index:05d}",
                tier=tier,
                plan=payload,
                execution_time_ms=milliseconds,
            )
        )
    return SyntheticWorkload(catalog=schema, samples=tuple(samples), tier=tier)


def curriculum_tier(epoch: int, total_epochs: int) -> int:
    """Blueprint curriculum: epochs 1-20 simple, 21-50 joins, 51+ complex.

    Short demo runs (``total_epochs <= 20``) compress the same simple -> joins
    -> complex progression into thirds so a 20-epoch checkpoint still sees all
    three tiers. The fixed 20/50 boundaries are preserved for full runs.
    """
    if total_epochs <= 0:
        raise ValueError("total_epochs must be positive")
    if epoch < 1:
        raise ValueError("epoch must be positive")
    if total_epochs <= 20:
        first = math.ceil(total_epochs / 3)
        second = math.ceil(2 * total_epochs / 3)
        if epoch <= first:
            return 1
        if epoch <= second:
            return 2
        return 3
    if epoch <= 20:
        return 1
    if epoch <= 50:
        return 2
    return 3
