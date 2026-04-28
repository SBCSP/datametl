"""Engine-agnostic schema model.

Every introspector (Postgres today; MySQL/etc. later) produces a `Schema` of this shape.
Downstream code — comparison, mapping, frontend — never knows what engine produced it,
which is what makes cross-engine support tractable.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Normalized type vocabulary. Engine-specific introspectors map their native types into these.
# Keep the set small; the mapping registry decides how each maps back to a destination's native type.
NormalizedType = Literal[
    "string",        # text / varchar / char
    "int16",
    "int32",
    "int64",
    "float32",
    "float64",
    "decimal",
    "boolean",
    "uuid",
    "json",          # json or jsonb
    "binary",        # bytea / blob
    "date",
    "time",
    "timestamp",     # without timezone
    "timestamptz",   # with timezone
    "interval",
    "array",
    "enum",
    "geometry",
    "unknown",
]

Engine = Literal["postgres"]


class ForeignKeyRef(BaseModel):
    schema_: str = Field(alias="schema")
    table: str
    column: str

    model_config = {"populate_by_name": True}


class Column(BaseModel):
    name: str
    native_type: str                    # e.g. "character varying(255)"
    normalized_type: NormalizedType
    nullable: bool
    default: str | None = None
    is_primary_key: bool = False
    foreign_key: ForeignKeyRef | None = None


class Index(BaseModel):
    name: str
    columns: list[str]
    unique: bool = False


class Table(BaseModel):
    schema_: str = Field(alias="schema")
    name: str
    columns: list[Column]
    indexes: list[Index] = Field(default_factory=list)
    row_count_estimate: int | None = None
    rls_enabled: bool = False           # populated for Postgres

    model_config = {"populate_by_name": True}

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_}.{self.name}"


class RlsPolicy(BaseModel):
    schema_: str = Field(alias="schema")
    table: str
    name: str
    command: str                        # SELECT / INSERT / UPDATE / DELETE / ALL
    using_expr: str | None = None
    with_check_expr: str | None = None
    permissive: bool = True

    model_config = {"populate_by_name": True}


class View(BaseModel):
    schema_: str = Field(alias="schema")
    name: str
    definition: str

    model_config = {"populate_by_name": True}


class Schema(BaseModel):
    engine: Engine
    server_version: str
    tables: list[Table]
    views: list[View] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    rls_policies: list[RlsPolicy] = Field(default_factory=list)


class Warning(BaseModel):
    """Surfaced by recipes (e.g. Supabase recipe). Frontend renders these as banners/badges."""

    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    target: str | None = None           # e.g. "schema:auth", "table:public.posts", "column:public.posts.id"
