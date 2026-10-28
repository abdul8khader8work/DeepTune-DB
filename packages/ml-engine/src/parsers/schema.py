"""Schema statistics used by symbolic pruning and graph features."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: Heap tuple header (t_xmin, t_xmax, t_ctid, ...) in bytes.
TUPLE_HEADER_BYTES = 24
#: Fill factor and page headers inflate the on-disk relation size.
PAGE_OVERHEAD_RATIO = 1.25

_DEFAULT_WIDTHS: tuple[tuple[str, int], ...] = (
    ("bool", 1),
    ("int2", 2),
    ("int4", 4),
    ("int8", 8),
    ("serial", 4),
    ("bigserial", 8),
    ("numeric", 12),
    ("real", 4),
    ("double", 8),
    ("timestamp", 8),
    ("date", 4),
    ("time", 8),
    ("uuid", 16),
    ("json", 64),
    ("text", 32),
    ("char", 16),
)


def _type_matches(data_type: str, token: str) -> bool:
    return token in data_type


def is_boolean_type(data_type: str) -> bool:
    normalized = data_type.lower()
    return normalized in {"bool", "boolean"} or normalized.startswith("bool")


def is_json_type(data_type: str) -> bool:
    normalized = data_type.lower()
    return normalized.startswith("json") or "jsonb" in normalized


def is_text_type(data_type: str) -> bool:
    normalized = data_type.lower()
    return "char" in normalized or "text" in normalized


def estimate_column_width(data_type: str) -> int:
    """Rough per-column width for storage estimates when the DB gives none."""
    normalized = data_type.lower()
    for token, width in _DEFAULT_WIDTHS:
        if _type_matches(normalized, token):
            return width
    return 16


@dataclass(frozen=True)
class ColumnStats:
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    n_distinct: int | None = None
    existing_indexes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_boolean(self) -> bool:
        return is_boolean_type(self.data_type)

    @property
    def is_json(self) -> bool:
        return is_json_type(self.data_type)

    @property
    def is_text(self) -> bool:
        return is_text_type(self.data_type)

    @property
    def width_bytes(self) -> int:
        return estimate_column_width(self.data_type)


@dataclass(frozen=True)
class TableStats:
    name: str
    schema_name: str = "public"
    row_count: int = 0
    total_bytes: int = 0
    is_write_heavy: bool = False
    columns: tuple[ColumnStats, ...] = field(default_factory=tuple)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.name}"

    @property
    def avg_row_bytes(self) -> int:
        if self.columns:
            return max(8, sum(column.width_bytes for column in self.columns))
        return 16

    @property
    def estimated_heap_bytes(self) -> int:
        """Relation size in bytes.

        ``pg_total_relation_size`` when the catalog carries it; otherwise a
        column-width estimate that includes the 24-byte tuple header and page
        overhead, which the raw column sum omits by ~40%.
        """
        if self.total_bytes > 0:
            return self.total_bytes
        rows = max(0, self.row_count)
        return int(rows * (self.avg_row_bytes + TUPLE_HEADER_BYTES) * PAGE_OVERHEAD_RATIO)

    @property
    def effective_bytes(self) -> int:
        return self.estimated_heap_bytes

    def column(self, name: str) -> ColumnStats | None:
        lowered = name.lower()
        for column in self.columns:
            if column.name.lower() == lowered:
                return column
        return None


@dataclass(frozen=True)
class SchemaCatalog:
    """Lookup wrapper around the API's `/schema` payload."""

    tables: tuple[TableStats, ...] = field(default_factory=tuple)

    def table(self, schema_name: str, name: str) -> TableStats | None:
        lowered = name.lower()
        for table in self.tables:
            if table.name.lower() == lowered and table.schema_name.lower() == schema_name.lower():
                return table
        return None

    def find(self, name: str) -> TableStats | None:
        lowered = name.lower()
        for table in self.tables:
            if table.name.lower() == lowered:
                return table
        return None

    @property
    def total_bytes(self) -> int:
        return sum(table.effective_bytes for table in self.tables)

    @classmethod
    def from_api_tables(cls, tables: list[Mapping[str, Any]]) -> "SchemaCatalog":
        """Build a catalog from the Phase 2 `SchemaResponse.tables` shape."""
        parsed: list[TableStats] = []
        for raw in tables:
            columns = tuple(
                ColumnStats(
                    name=str(column["name"]),
                    data_type=str(column.get("data_type", "text")),
                    is_nullable=bool(column.get("is_nullable", True)),
                    is_primary_key=bool(column.get("is_primary_key", False)),
                    n_distinct=(
                        int(column["n_distinct"])
                        if column.get("n_distinct") is not None
                        else None
                    ),
                    existing_indexes=tuple(
                        str(name) for name in column.get("existing_indexes", ())
                    ),
                )
                for column in raw.get("columns", ())
            )
            parsed.append(
                TableStats(
                    name=str(raw["name"]),
                    schema_name=str(raw.get("schema_name", "public")),
                    row_count=int(raw.get("row_estimate", raw.get("row_count", 0)) or 0),
                    total_bytes=int(raw.get("total_bytes", 0) or 0),
                    is_write_heavy=bool(raw.get("is_write_heavy", False)),
                    columns=columns,
                )
            )
        return cls(tables=tuple(parsed))
