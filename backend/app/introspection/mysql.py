"""MySQL introspector — produces the same normalized Schema as the Postgres one.

Uses SQLAlchemy's engine-agnostic `Inspector` for structure (tables, columns, PKs, FKs,
indexes, views) and a single `information_schema.tables` query for row-count estimates. MySQL
has no RLS or extensions, so those come back empty.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy import Engine, inspect, text

from app.introspection.normalized import (
    Column,
    ForeignKeyRef,
    Index,
    NormalizedType,
    Schema,
    Table,
    View,
)

log = logging.getLogger("datametl.introspect")

SYSTEM_SCHEMAS = frozenset({"information_schema", "mysql", "performance_schema", "sys"})


def _normalize_mysql_type(native: str) -> NormalizedType:
    """Map a MySQL native type string to the shared normalized vocabulary."""
    t = native.lower().strip()
    # tinyint(1) is MySQL's boolean convention.
    if re.match(r"^tinyint\(\s*1\s*\)", t):
        return "boolean"
    # Drop display width / precision and unsigned/zerofill modifiers.
    base = re.sub(r"\(.*\)", "", t.replace("unsigned", "").replace("zerofill", "")).strip()

    match base:
        case "tinyint" | "smallint" | "year":
            return "int16"
        case "mediumint" | "int" | "integer":
            return "int32"
        case "bigint":
            return "int64"
        case "float":
            return "float32"
        case "double" | "double precision" | "real":
            return "float64"
        case "decimal" | "numeric" | "dec" | "fixed":
            return "decimal"
        case "bool" | "boolean":
            return "boolean"
        case "char" | "varchar" | "tinytext" | "text" | "mediumtext" | "longtext" | "nchar" | "nvarchar":
            return "string"
        case "json":
            return "json"
        case "binary" | "varbinary" | "tinyblob" | "blob" | "mediumblob" | "longblob" | "bit":
            return "binary"
        case "date":
            return "date"
        case "time":
            return "time"
        case "datetime" | "timestamp":
            return "timestamp"
        case "enum":
            return "enum"
        case "set":
            return "string"
        case ("geometry" | "point" | "linestring" | "polygon" | "multipoint"
              | "multilinestring" | "multipolygon" | "geometrycollection"):
            return "geometry"
        case _:
            return "unknown"


def introspect(engine: Engine) -> Schema:
    started = time.monotonic()
    insp = inspect(engine)
    with engine.connect() as conn:
        server_version = conn.execute(text("SELECT VERSION()")).scalar_one()
        all_schemas = [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]
        log.info("introspect(mysql): server=%s schemas=%s", server_version, all_schemas)

        # Row-count estimates for every base table in one shot (TABLE_ROWS is an estimate).
        est = conn.execute(
            text(
                "SELECT table_schema, table_name, table_rows "
                "FROM information_schema.tables WHERE table_type = 'BASE TABLE'"
            )
        ).all()
        row_estimates = {(r[0], r[1]): int(r[2] or 0) for r in est}

        tables: list[Table] = []
        views: list[View] = []
        for schema_name in all_schemas:
            for table_name in insp.get_table_names(schema=schema_name):
                tables.append(
                    Table(
                        schema=schema_name,
                        name=table_name,
                        columns=_columns(insp, schema_name, table_name),
                        indexes=_indexes(insp, schema_name, table_name),
                        row_count_estimate=row_estimates.get((schema_name, table_name)),
                        rls_enabled=False,
                    )
                )
            for view_name in insp.get_view_names(schema=schema_name):
                definition = insp.get_view_definition(view_name, schema=schema_name) or ""
                views.append(View(schema=schema_name, name=view_name, definition=definition))

    log.info(
        "introspect(mysql): done in %.2fs (%d tables, %d views)",
        time.monotonic() - started, len(tables), len(views),
    )
    return Schema(
        engine="mysql",
        server_version=str(server_version),
        tables=tables,
        views=views,
        extensions=[],
        rls_policies=[],
    )


def _columns(insp: Any, schema: str, table: str) -> list[Column]:
    pk_cols = set(insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or [])
    fks = {
        c: ForeignKeyRef(
            schema=fk.get("referred_schema") or schema,  # MySQL FKs are usually same-schema
            table=fk["referred_table"],
            column=fk["referred_columns"][0],
        )
        for fk in insp.get_foreign_keys(table, schema=schema)
        if fk.get("referred_table") and fk.get("referred_columns")
        for c in fk["constrained_columns"]
    }

    cols: list[Column] = []
    for col in insp.get_columns(table, schema=schema):
        native = str(col["type"])
        cols.append(
            Column(
                name=col["name"],
                native_type=native,
                normalized_type=_normalize_mysql_type(native),
                nullable=bool(col.get("nullable", True)),
                default=str(col["default"]) if col.get("default") is not None else None,
                is_primary_key=col["name"] in pk_cols,
                foreign_key=fks.get(col["name"]),
            )
        )
    return cols


def _indexes(insp: Any, schema: str, table: str) -> list[Index]:
    out: list[Index] = []
    for idx in insp.get_indexes(table, schema=schema):
        if not idx.get("name"):
            continue
        cols = [c if c is not None else "(expression)" for c in (idx.get("column_names") or [])]
        out.append(Index(name=idx["name"], columns=cols, unique=bool(idx.get("unique"))))
    return out
