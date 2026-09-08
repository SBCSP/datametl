"""SQL Server introspector — produces the same normalized Schema as Postgres/MySQL.

Uses SQLAlchemy's engine-agnostic `Inspector` for structure and `sys.partitions` for
row-count estimates. SQL Server has no RLS/extensions in the Postgres sense, so those
come back empty.
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

# Built-in schemas / database principals that are not user data.
SYSTEM_SCHEMAS = frozenset(
    {
        "sys",
        "INFORMATION_SCHEMA",
        "guest",
        "db_owner",
        "db_accessadmin",
        "db_securityadmin",
        "db_ddladmin",
        "db_backupoperator",
        "db_datareader",
        "db_datawriter",
        "db_denydatareader",
        "db_denydatawriter",
    }
)


def _normalize_mssql_type(native: str) -> NormalizedType:
    """Map a SQL Server native type string to the shared normalized vocabulary."""
    t = native.lower().strip()
    base = re.sub(r"\(.*\)", "", t).strip()
    # Collapse spaced type names SQLAlchemy may emit.
    base = re.sub(r"\s+", " ", base)

    match base:
        case "tinyint" | "smallint":
            return "int16"
        case "int" | "integer":
            return "int32"
        case "bigint":
            return "int64"
        case "real" | "float(24)":
            return "float32"
        case "float" | "float(53)" | "double precision":
            return "float64"
        case "decimal" | "numeric" | "money" | "smallmoney":
            return "decimal"
        case "bit":
            return "boolean"
        case "char" | "varchar" | "text" | "nchar" | "nvarchar" | "ntext" | "sysname" | "xml":
            return "string"
        case "uniqueidentifier":
            return "uuid"
        case "json":  # SQL Server 2025+ / Azure; older versions store JSON as nvarchar
            return "json"
        case "binary" | "varbinary" | "image" | "timestamp" | "rowversion":
            # timestamp/rowversion are binary(8) concurrency tokens, not datetime.
            return "binary"
        case "date":
            return "date"
        case "time":
            return "time"
        case "datetime" | "datetime2" | "smalldatetime":
            return "timestamp"
        case "datetimeoffset":
            return "timestamptz"
        case "geography" | "geometry":
            return "geometry"
        case "sql_variant" | "hierarchyid" | "cursor":
            return "unknown"
        case _:
            return "unknown"


def introspect(engine: Engine) -> Schema:
    started = time.monotonic()
    insp = inspect(engine)
    with engine.connect() as conn:
        server_version = conn.execute(text("SELECT @@VERSION")).scalar_one()
        version_line = (
            str(server_version).splitlines()[0].strip() if server_version else "SQL Server"
        )
        all_schemas = [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]
        log.info("introspect(mssql): server=%s schemas=%s", version_line, all_schemas)

        # Row counts from sys.partitions (heap + clustered index).
        est = conn.execute(
            text(
                """
                SELECT s.name AS schema_name, t.name AS table_name, SUM(p.rows) AS row_count
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
                GROUP BY s.name, t.name
                """
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
                definition = ""
                try:
                    definition = insp.get_view_definition(view_name, schema=schema_name) or ""
                except Exception:
                    definition = ""
                views.append(View(schema=schema_name, name=view_name, definition=definition))

    log.info(
        "introspect(mssql): done in %.2fs (%d tables, %d views)",
        time.monotonic() - started,
        len(tables),
        len(views),
    )
    return Schema(
        engine="mssql",
        server_version=version_line,
        tables=tables,
        views=views,
        extensions=[],
        rls_policies=[],
    )


def _columns(insp: Any, schema: str, table: str) -> list[Column]:
    pk_cols = set(insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or [])
    fks = {
        c: ForeignKeyRef(
            schema=fk.get("referred_schema") or schema,
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
                normalized_type=_normalize_mssql_type(native),
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
