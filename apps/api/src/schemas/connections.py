"""Database connection and schema contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SSLMode = Literal["disable", "allow", "prefer", "require"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class DBConnectionRequest(StrictModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    dbname: str = Field(min_length=1, max_length=63)
    user: str = Field(min_length=1, max_length=63)
    password: str = Field(min_length=1, max_length=512)
    ssl_mode: SSLMode = "prefer"


class ConnectionResponse(StrictModel):
    connection_id: str
    status: str
    db_version: str


class ColumnSchema(StrictModel):
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    existing_indexes: list[str]


class TableSchema(StrictModel):
    name: str
    schema_name: str
    row_estimate: int
    #: ``pg_total_relation_size``; 0 when the role cannot read relation sizes.
    total_bytes: int = 0
    columns: list[ColumnSchema]


class SchemaResponse(StrictModel):
    connection_id: str
    tables: list[TableSchema]
