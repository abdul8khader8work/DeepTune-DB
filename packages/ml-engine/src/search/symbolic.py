"""Symbolic engine: deterministic candidate generation and pruning.

Search-space reduction is the first half of the neuro-symbolic contract. The
rules here are intentionally conservative: a candidate that cannot be justified
from the catalog and the parsed predicates never reaches the GNN.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Iterable

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from config import (
    GOAL_MAX_COLUMNS,
    INDEX_ROW_OVERHEAD_BYTES,
    MAX_CANDIDATES,
    MAX_INDEXES_PER_WRITE_TABLE,
    STORAGE_BUDGET_RATIO,
    WRITE_HEAVY_IMPACT,
)
from parsers.schema import ColumnStats, SchemaCatalog, TableStats
from search.types import (
    ColumnRef,
    IndexCandidate,
    IndexMethod,
    Predicate,
    PredicateKind,
    PruningRejection,
    SymbolicResult,
    TableRef,
)

_KIND_PRIORITY: dict[PredicateKind, float] = {
    "equality": 4.0,
    "join": 3.0,
    "range": 2.0,
    "grouping": 1.0,
    "ordering": 1.0,
}

_JSON_OPERATORS = frozenset({"@>", "<@", "?", "?|", "?&", "->", "->>"})

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Copy,
    exp.Merge,
    exp.Into,
    exp.Lock,
)


class SymbolicError(ValueError):
    """Raised when the symbolic engine cannot parse the query."""


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _index_name(table: TableStats, columns: Iterable[str]) -> str:
    raw = f"idx_{table.name}_{'_'.join(columns)}".lower()
    safe = "".join(character if character.isalnum() or character == "_" else "_" for character in raw)
    return safe[:63]


def _parse_single_select(sql: str) -> exp.Expression:
    try:
        statements = parse(sql, read="postgres")
    except ParseError as exc:
        raise SymbolicError("Query could not be parsed as PostgreSQL") from exc
    if len(statements) != 1 or statements[0] is None:
        raise SymbolicError("Exactly one SQL statement is required")
    statement = statements[0]
    if statement.find(*_FORBIDDEN_NODES) is not None:
        raise SymbolicError("Only read-only SELECT statements are supported")
    if statement.find(exp.Select) is None:
        raise SymbolicError("Only read-only SELECT statements are supported")
    return statement


_COMPARISON_NODES = (
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
    exp.RegexpLike,
)

_JSON_NODES = (
    exp.ArrayContains,
    exp.ArrayContainsAll,
    exp.JSONBContains,
    exp.JSONBContainsAnyTopKeys,
    exp.JSONBContainsAllTopKeys,
    exp.JSONBExtract,
    exp.JSONBExtractScalar,
    exp.JSONBExists,
    exp.JSONExtract,
    exp.JSONExtractScalar,
)


def _json_operator(node: exp.Expression) -> str:
    """Recover the PostgreSQL operator from a parsed JSON predicate."""
    rendered = node.sql(dialect="postgres")
    for token in ("?&", "?|", "?", "@>", "<@", "->>", "->"):
        if token in rendered:
            return token
    return "@>"


def _predicate_kind(column: exp.Column) -> tuple[PredicateKind, str]:
    """Walk up to the nearest comparison/JSON operator around a column."""
    node: exp.Expression | None = column.parent
    while node is not None:
        if isinstance(node, _JSON_NODES):
            return "equality", _json_operator(node)
        if isinstance(node, _COMPARISON_NODES):
            if isinstance(node, (exp.EQ, exp.NullSafeEQ)):
                if len(list(node.find_all(exp.Column))) > 1:
                    return "join", "="
                return "equality", "="
            if isinstance(node, exp.In):
                return "equality", "IN"
            if isinstance(node, exp.Is):
                return "equality", "IS"
            if isinstance(node, exp.Between):
                return "range", "BETWEEN"
            if isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE)):
                return "range", node.key.upper()
            return "range", node.key.upper()
        node = node.parent
    return "equality", "filter"


def _table_ref(table: exp.Table) -> TableRef:
    return TableRef(schema=table.db or "public", name=table.name)


def _resolve_column(
    column: exp.Column,
    aliases: dict[str, TableRef],
    tables: tuple[TableRef, ...],
    catalog: SchemaCatalog,
) -> ColumnRef | None:
    if column.table:
        table = aliases.get(column.table)
        return ColumnRef(table=table, name=column.name) if table else None
    if len(tables) == 1:
        return ColumnRef(table=tables[0], name=column.name)
    matches = [
        table
        for table in tables
        if (stats := catalog.table(table.schema, table.name)) is not None
        and stats.column(column.name) is not None
    ]
    if len(matches) == 1:
        return ColumnRef(table=matches[0], name=column.name)
    return None


def extract_predicates(
    sql: str, catalog: SchemaCatalog
) -> tuple[tuple[Predicate, ...], tuple[TableRef, ...]]:
    """Parse WHERE/JOIN/GROUP BY/ORDER BY columns into typed predicates."""
    statement = _parse_single_select(sql)
    aliases: dict[str, TableRef] = {}
    table_map: dict[str, TableRef] = {}
    for table in statement.find_all(exp.Table):
        if not table.name:
            continue
        reference = _table_ref(table)
        aliases[table.alias_or_name] = reference
        aliases[table.name] = reference
        table_map[reference.qualified_name] = reference
    tables = tuple(table_map.values())

    seen: dict[tuple[str, str, str], Predicate] = {}

    def record(column: exp.Column, kind: PredicateKind, operator: str) -> None:
        resolved = _resolve_column(column, aliases, tables, catalog)
        if resolved is None:
            return
        key = (resolved.table.qualified_name, resolved.name.lower(), kind)
        existing = seen.get(key)
        if existing is None or _KIND_PRIORITY[kind] > _KIND_PRIORITY[existing.kind]:
            seen[key] = Predicate(column=resolved, kind=kind, operator=operator)

    where = statement.find(exp.Where)
    if where is not None:
        for column in where.find_all(exp.Column):
            kind, operator = _predicate_kind(column)
            record(column, kind, operator)

    for join in statement.find_all(exp.Join):
        condition = join.args.get("on")
        if condition is not None:
            for column in condition.find_all(exp.Column):
                record(column, "join", "=")

    group = statement.find(exp.Group)
    if group is not None:
        for column in group.find_all(exp.Column):
            record(column, "grouping", "GROUP BY")

    order = statement.find(exp.Order)
    if order is not None:
        for column in order.find_all(exp.Column):
            record(column, "ordering", "ORDER BY")

    predicates = tuple(
        sorted(
            seen.values(),
            key=lambda item: (
                item.column.table.qualified_name,
                -_KIND_PRIORITY[item.kind],
                item.column.name,
            ),
        )
    )
    return predicates, tables


def _access_method(
    columns: tuple[str, ...],
    kinds: tuple[PredicateKind, ...],
    stats: tuple[ColumnStats, ...],
    prefer_hash: bool = False,
) -> IndexMethod:
    """Map operators to access methods.

    Equality may use B-tree or Hash; B-tree is the default because it also
    supports ordering and covering scans. Ranges strictly require B-tree.
    JSON containment/text search requires GIN.
    """
    if any(column_stats.is_json for column_stats in stats):
        return "gin"
    if len(columns) == 1 and prefer_hash and all(kind == "equality" for kind in kinds):
        return "hash"
    return "btree"


def _storage_bytes(table: TableStats, column_count: int) -> int:
    return max(0, table.row_count) * (
        8 * column_count + INDEX_ROW_OVERHEAD_BYTES
    )


def _is_left_prefix(prefix: tuple[str, ...], ranked_columns: tuple[str, ...]) -> bool:
    """PostgreSQL can only use a composite index left-to-right."""
    return len(prefix) <= len(ranked_columns) and prefix == ranked_columns[: len(prefix)]


def generate_candidates(
    sql: str,
    catalog: SchemaCatalog,
    goal: str = "balanced",
    max_candidates: int = MAX_CANDIDATES,
    storage_budget_ratio: float = STORAGE_BUDGET_RATIO,
    prefer_hash: bool = False,
) -> SymbolicResult:
    """Generate valid index candidates and record every rejected alternative."""
    if goal not in GOAL_MAX_COLUMNS:
        raise SymbolicError(f"Unknown optimization goal: {goal}")

    predicates, tables = extract_predicates(sql, catalog)
    rejected: list[PruningRejection] = []
    if not predicates:
        return SymbolicResult(
            rejected=(PruningRejection("query", "no indexable predicates found"),),
            tables=tables,
        )

    by_table: dict[str, list[Predicate]] = defaultdict(list)
    for predicate in predicates:
        by_table[predicate.column.table.qualified_name].append(predicate)

    max_columns = GOAL_MAX_COLUMNS[goal]
    candidates: list[IndexCandidate] = []

    for table_key, table_predicates in by_table.items():
        reference = table_predicates[0].column.table
        table = catalog.table(reference.schema, reference.name)
        if table is None:
            rejected.append(
                PruningRejection(table_key, "table is absent from the schema catalog")
            )
            continue

        column_best: dict[str, tuple[float, Predicate]] = {}
        for predicate in table_predicates:
            current = column_best.get(predicate.column.name.lower())
            priority = _KIND_PRIORITY[predicate.kind]
            if current is None or priority > current[0]:
                column_best[predicate.column.name.lower()] = (priority, predicate)

        ranked: list[tuple[str, Predicate]] = []
        for column_name, (priority, predicate) in column_best.items():
            column_stats = table.column(column_name)
            if column_stats is None:
                rejected.append(
                    PruningRejection(
                        f"{table_key}.{column_name}", "column is absent from the catalog"
                    )
                )
                continue
            if column_stats.is_boolean:
                rejected.append(
                    PruningRejection(
                        f"{table_key}.{column_name}",
                        "boolean columns are not indexed (low selectivity)",
                    )
                )
                continue
            if column_stats.is_json and predicate.operator not in _JSON_OPERATORS:
                rejected.append(
                    PruningRejection(
                        f"{table_key}.{column_name}",
                        "JSONB columns require containment operators for GIN",
                    )
                )
                continue
            if (
                column_stats.n_distinct is not None
                and table.row_count > 0
                and column_stats.n_distinct / table.row_count < 0.05
            ):
                rejected.append(
                    PruningRejection(
                        f"{table_key}.{column_name}",
                        "distinct ratio below 5% (low selectivity)",
                    )
                )
                continue
            ranked.append((column_name, predicate))

        ranked.sort(key=lambda item: (-_KIND_PRIORITY[item[1].kind], item[0]))
        ranked_columns = tuple(column_name for column_name, _ in ranked)
        if not ranked_columns:
            continue

        table_candidates = 0
        for length in range(1, max_columns + 1):
            prefix = ranked_columns[:length]
            if len(prefix) < length:
                break
            if not _is_left_prefix(prefix, ranked_columns):
                rejected.append(
                    PruningRejection(
                        f"{table_key}({', '.join(prefix)})", "left-prefix rule violation"
                    )
                )
                continue

            prefix_predicates = tuple(
                predicate
                for column_name, predicate in ranked
                if column_name in prefix
            )
            prefix_kinds = tuple(
                predicate.kind
                for column_name, predicate in ranked
                if column_name in prefix
            )
            prefix_stats = tuple(
                table.column(column_name) or ColumnStats(column_name, "text")
                for column_name in prefix
            )
            if prefix[0] and len(prefix) > 1 and ranked[0][1].kind == "ordering":
                rejected.append(
                    PruningRejection(
                        f"{table_key}({', '.join(prefix)})",
                        "left-prefix rule: ordering-only column cannot lead a composite index",
                    )
                )
                continue

            method = _access_method(prefix, prefix_kinds, prefix_stats, prefer_hash)
            if method == "gin" and len(prefix) > 1:
                rejected.append(
                    PruningRejection(
                        f"{table_key}({', '.join(prefix)})",
                        "GIN candidates must be single-column",
                    )
                )
                continue

            storage = _storage_bytes(table, len(prefix))
            if (
                table.effective_bytes > 0
                and storage > table.effective_bytes * storage_budget_ratio
            ):
                rejected.append(
                    PruningRejection(
                        f"{table_key}({', '.join(prefix)})",
                        "storage overhead exceeds "
                        f"{storage_budget_ratio:.0%} of the table",
                    )
                )
                continue

            if (
                len(prefix) == 1
                and prefix_stats[0].existing_indexes
            ):
                rejected.append(
                    PruningRejection(
                        f"{table_key}.{prefix[0]}", "column already has an index"
                    )
                )
                continue

            priority = sum(
                _KIND_PRIORITY[predicate.kind] for predicate in prefix_predicates
            )
            name = _index_name(table, prefix)
            create_sql = (
                f"CREATE INDEX CONCURRENTLY {quote_identifier(name)} "
                f"ON {quote_identifier(table.schema_name)}.{quote_identifier(table.name)} "
                f"USING {method} "
                f"({', '.join(quote_identifier(column) for column in prefix)})"
            )
            write_impact = 0.8 + 0.7 * len(prefix)
            if table.is_write_heavy:
                write_impact *= 1.0 + WRITE_HEAVY_IMPACT
            candidate = IndexCandidate(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{table_key}:{method}:{prefix}")),
                table=TableRef(schema=table.schema_name, name=table.name),
                columns=prefix,
                method=method,
                create_sql=create_sql,
                storage_bytes=storage,
                write_impact_percentage=round(write_impact, 2),
                priority=priority,
                reason=(
                    f"{method.upper()} index on {table.qualified_name}"
                    f"({', '.join(prefix)}) from "
                    + ", ".join(
                        f"{predicate.kind}:{predicate.column.name}"
                        for predicate in prefix_predicates
                    )
                ),
            )
            candidates.append(candidate)
            table_candidates += 1
            if table.is_write_heavy and table_candidates >= MAX_INDEXES_PER_WRITE_TABLE:
                rejected.append(
                    PruningRejection(
                        table_key,
                        f"write-heavy table capped at {MAX_INDEXES_PER_WRITE_TABLE} indexes",
                    )
                )
                break

    deduped: dict[str, IndexCandidate] = {}
    for candidate in candidates:
        deduped.setdefault(candidate.id, candidate)
    ordered = sorted(
        deduped.values(),
        key=lambda item: (-item.priority, item.table.qualified_name, item.columns),
    )
    return SymbolicResult(
        candidates=tuple(ordered[:max_candidates]),
        rejected=tuple(rejected),
        tables=tables,
    )
