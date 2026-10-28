"""Single-query schema introspection (no N+1)."""

import json
from typing import Any

import asyncpg

from src.schemas.connections import ColumnSchema, TableSchema

_SCHEMA_QUERY = """
SELECT
    t.table_schema,
    t.table_name,
    GREATEST(COALESCE(pc.reltuples, 0), 0)::bigint AS row_estimate,
    COALESCE(pg_total_relation_size(pc.oid), 0)::bigint AS total_bytes,
    json_agg(
        json_build_object(
            'name', c.column_name,
            'data_type', c.data_type,
            'is_nullable', (c.is_nullable = 'YES'),
            'is_primary_key', (pk.column_name IS NOT NULL),
            'existing_indexes', COALESCE(ix.index_names, ARRAY[]::text[])
        )
        ORDER BY c.ordinal_position
    ) AS columns
FROM information_schema.tables AS t
JOIN information_schema.columns AS c
    ON c.table_schema = t.table_schema
   AND c.table_name = t.table_name
LEFT JOIN pg_namespace AS n
    ON n.nspname = t.table_schema
LEFT JOIN pg_class AS pc
    ON pc.relnamespace = n.oid
   AND pc.relname = t.table_name
LEFT JOIN LATERAL (
    SELECT kcu.column_name
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
        ON kcu.constraint_name = tc.constraint_name
       AND kcu.constraint_schema = tc.constraint_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema = t.table_schema
      AND tc.table_name = t.table_name
      AND kcu.column_name = c.column_name
    LIMIT 1
) AS pk ON true
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT idx.indexname) AS index_names
    FROM pg_indexes AS idx
    JOIN pg_class AS ic
        ON ic.relname = idx.indexname
    JOIN pg_namespace AS ins
        ON ins.oid = ic.relnamespace
       AND ins.nspname = idx.schemaname
    JOIN pg_index AS ii
        ON ii.indexrelid = ic.oid
    JOIN pg_attribute AS ia
        ON ia.attrelid = ii.indrelid
       AND ia.attnum = ANY (ii.indkey::smallint[])
    WHERE idx.schemaname = t.table_schema
      AND idx.tablename = t.table_name
      AND ia.attname = c.column_name
) AS ix ON true
WHERE t.table_type = 'BASE TABLE'
  AND ($1::boolean OR t.table_schema = 'public')
GROUP BY t.table_schema, t.table_name, pc.reltuples, pc.oid
ORDER BY t.table_schema, t.table_name
"""


def _as_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


async def fetch_schema(
    conn: asyncpg.Connection, include_system_tables: bool = False
) -> list[TableSchema]:
    rows = await conn.fetch(_SCHEMA_QUERY, include_system_tables)
    tables: list[TableSchema] = []
    for row in rows:
        columns = [
            ColumnSchema(
                name=str(item["name"]),
                data_type=str(item["data_type"]),
                is_nullable=bool(item["is_nullable"]),
                is_primary_key=bool(item["is_primary_key"]),
                existing_indexes=[str(name) for name in item.get("existing_indexes", [])],
            )
            for item in _as_list(row["columns"])
        ]
        tables.append(
            TableSchema(
                name=str(row["table_name"]),
                schema_name=str(row["table_schema"]),
                row_estimate=int(row["row_estimate"]),
                total_bytes=int(row["total_bytes"]),
                columns=columns,
            )
        )
    return tables
