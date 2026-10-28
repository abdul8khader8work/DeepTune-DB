"""Connection lifecycle and schema introspection."""

import uuid

import asyncpg
from fastapi import APIRouter, Depends, Request

from src.api.deps import get_state, require_auth
from src.core.errors import not_found
from src.core.security import build_dsn
from src.db.target import StoredConnection, connect_target
from src.schemas.connections import (
    ConnectionResponse,
    DBConnectionRequest,
    SchemaResponse,
)
from src.schemas.system import DeleteResponse
from src.services.introspection import fetch_schema

router = APIRouter(
    prefix="/databases",
    tags=["databases"],
    dependencies=[Depends(require_auth)],
)


@router.post("/connect", response_model=ConnectionResponse)
async def connect_database(
    payload: DBConnectionRequest, request: Request
) -> ConnectionResponse:
    state = get_state(request)
    dsn = build_dsn(
        host=payload.host,
        port=payload.port,
        dbname=payload.dbname,
        user=payload.user,
        password=payload.password,
    )
    stored = StoredConnection(dsn=dsn, ssl_mode=payload.ssl_mode)
    connection = await connect_target(stored, state.settings)
    try:
        version = await connection.fetchval("SHOW server_version")
    except asyncpg.PostgresError:
        version = None
    finally:
        await connection.close()

    connection_id = str(uuid.uuid4())
    await state.store.save(connection_id, dsn, payload.ssl_mode)
    return ConnectionResponse(
        connection_id=connection_id,
        status="connected",
        db_version=f"PostgreSQL {version}" if version else "PostgreSQL",
    )


@router.get("/{connection_id}/schema", response_model=SchemaResponse)
async def get_database_schema(
    connection_id: str, request: Request
) -> SchemaResponse:
    state = get_state(request)
    stored = await state.store.get(connection_id)
    if stored is None:
        raise not_found(
            "CONNECTION_NOT_FOUND",
            "No stored connection matches that connection_id.",
        )
    connection = await connect_target(stored, state.settings)
    try:
        tables = await fetch_schema(connection)
    finally:
        await connection.close()
    return SchemaResponse(connection_id=connection_id, tables=tables)


@router.delete("/{connection_id}", response_model=DeleteResponse)
async def delete_database(connection_id: str, request: Request) -> DeleteResponse:
    state = get_state(request)
    removed = await state.store.delete(connection_id)
    if not removed:
        raise not_found(
            "CONNECTION_NOT_FOUND",
            "No stored connection matches that connection_id.",
        )
    return DeleteResponse(status="deleted", connection_id=connection_id)
