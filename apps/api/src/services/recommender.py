"""Heuristic index candidates derived from the sqlglot AST.

Phase 2 produces candidates and validates them with hypopg. Phase 3 replaces the
heuristic ordering with GNN scoring; the API contract stays identical.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import uuid4

from sqlglot import exp

from src.schemas.analysis import IndexRecommendation, OptimizationGoal
from src.schemas.connections import TableSchema
from src.services.sql_guard import ValidatedSql


@dataclass
class TablePredicates:
    equality: list[str] = field(default_factory=list)
    join: list[str] = field(default_factory=list)
    range: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)


_GOAL_LIMITS: dict[OptimizationGoal, tuple[int, int]] = {
    "minimal_storage": (1, 1),
    "balanced": (2, 2),
    "read_performance": (3, 3),
}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _index_name(table: str, columns: list[str]) -> str:
    raw = f"idx_{table}_{'_'.join(columns)}".lower()
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in raw)
    return safe[:63]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _table_lookup(statement: exp.Expression) -> tuple[dict[str, exp.Table], exp.Table | None]:
    alias_map: dict[str, exp.Table] = {}
    distinct: dict[str, exp.Table] = {}
    for table in statement.find_all(exp.Table):
        if not table.name:
            continue
        alias_map[table.alias_or_name] = table
        alias_map[table.name] = table
        distinct[table.name] = table
    only = next(iter(distinct.values())) if len(distinct) == 1 else None
    return alias_map, only


def _resolve(
    column: exp.Column,
    alias_map: dict[str, exp.Table],
    fallback: exp.Table | None,
) -> tuple[str, str] | None:
    table = alias_map.get(column.table) if column.table else fallback
    if table is None:
        return None
    return (table.db or "public", table.name)


def _bucket_for(column: exp.Column) -> str:
    ancestor = column.find_ancestor(
        exp.EQ,
        exp.NullSafeEQ,
        exp.In,
        exp.Is,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.Between,
        exp.Like,
        exp.ILike,
    )
    if ancestor is None:
        return "equality"
    if isinstance(ancestor, (exp.EQ, exp.NullSafeEQ)):
        if len(list(ancestor.find_all(exp.Column))) > 1:
            return "join"
        return "equality"
    if isinstance(ancestor, (exp.In, exp.Is)):
        return "equality"
    return "range"


def _collect_predicates(
    validated: ValidatedSql,
) -> dict[tuple[str, str], TablePredicates]:
    statement = validated.statement
    alias_map, fallback = _table_lookup(statement)
    predicates: dict[tuple[str, str], TablePredicates] = defaultdict(TablePredicates)

    def add(expression: exp.Expression, bucket: str) -> None:
        for column in expression.find_all(exp.Column):
            key = _resolve(column, alias_map, fallback)
            if key is None:
                continue
            getattr(predicates[key], bucket).append(column.name)

    where = statement.find(exp.Where)
    if where is not None:
        for column in where.find_all(exp.Column):
            add(column, _bucket_for(column))

    for join in statement.find_all(exp.Join):
        condition = join.args.get("on")
        if condition is not None:
            add(condition, "join")

    group = statement.find(exp.Group)
    if group is not None:
        add(group, "ordering")

    order = statement.find(exp.Order)
    if order is not None:
        add(order, "ordering")

    return predicates


def recommend_indexes(
    validated: ValidatedSql,
    tables: list[TableSchema],
    goal: OptimizationGoal = "balanced",
) -> list[IndexRecommendation]:
    max_columns, max_recommendations = _GOAL_LIMITS[goal]
    table_map = {(table.schema_name, table.name): table for table in tables}
    predicates = _collect_predicates(validated)

    candidates: list[tuple[int, IndexRecommendation]] = []
    for (schema_name, table_name), bucket in predicates.items():
        table = table_map.get((schema_name, table_name))
        if table is None:
            continue

        columns = _dedupe(
            bucket.equality + bucket.join + bucket.range + bucket.ordering
        )[:max_columns]
        if not columns:
            continue

        score = (
            len(bucket.equality) * 3
            + len(bucket.join) * 2
            + len(bucket.range)
        )
        name = _index_name(table_name, columns)
        sql = (
            f"CREATE INDEX CONCURRENTLY {_quote(name)} "
            f"ON {_quote(schema_name)}.{_quote(table_name)} "
            f"({', '.join(_quote(column) for column in columns)})"
        )
        rows = max(table.row_estimate, 0)
        storage = rows * (8 * len(columns) + 6)
        has_join = bool(bucket.join)

        candidate = IndexRecommendation(
            id=str(uuid4()),
            sql_statement=sql,
            target_table=table_name,
            target_columns=columns,
            predicted_speedup_factor=round(
                1.0 + 0.8 * len(columns) + (0.5 if has_join else 0.0), 2
            ),
            validated_speedup_factor=None,
            storage_overhead_bytes=int(storage),
            write_impact_percentage=round(0.8 + 0.7 * len(columns), 1),
            confidence_score=round(
                min(0.95, 0.55 + 0.12 * len(columns) + (0.08 if has_join else 0.0)), 2
            ),
            explanation=(
                f"Heuristic candidate for {schema_name}.{table_name}: "
                f"{len(bucket.equality)} equality, {len(bucket.join)} join, "
                f"{len(bucket.range)} range predicate(s). Validated with hypopg "
                f"before it is shown as a recommendation."
            ),
        )
        candidates.append((score, candidate))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates[:max_recommendations]]
