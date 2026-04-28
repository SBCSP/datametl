"""Postgres introspector — produces a normalized Schema from a live database.

Uses SQLAlchemy `Inspector` for the structural bits and raw `pg_catalog` queries for
Postgres-specific things (extensions, RLS policies, view definitions, row count estimates).
"""
from __future__ import annotations

import logging
import re
import time

from sqlalchemy import Engine, inspect, text

log = logging.getLogger("datametl.introspect")

from app.introspection.normalized import (
    Column,
    ForeignKeyRef,
    Index,
    NormalizedType,
    RlsPolicy,
    Schema,
    Table,
    View,
)

# Schemas that are noise unless explicitly opted in. Most datametl users don't want pg_catalog
# / information_schema / pg_toast in their introspection output.
SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})


def _normalize_type(native: str) -> NormalizedType:
    """Map a Postgres native type string to our normalized vocabulary."""
    t = native.lower().strip()
    # strip parameters: "character varying(255)" -> "character varying"
    base = re.sub(r"\s*\(.*\)\s*$", "", t).strip()

    if base.endswith("[]") or base.startswith("_"):
        return "array"

    match base:
        case "text" | "character varying" | "varchar" | "character" | "char" | "name" | "citext":
            return "string"
        case "smallint" | "int2":
            return "int16"
        case "integer" | "int" | "int4":
            return "int32"
        case "bigint" | "int8":
            return "int64"
        case "real" | "float4":
            return "float32"
        case "double precision" | "float8":
            return "float64"
        case "numeric" | "decimal" | "money":
            return "decimal"
        case "boolean" | "bool":
            return "boolean"
        case "uuid":
            return "uuid"
        case "json" | "jsonb":
            return "json"
        case "bytea":
            return "binary"
        case "date":
            return "date"
        case "time" | "time without time zone" | "time with time zone" | "timetz":
            return "time"
        case "timestamp" | "timestamp without time zone":
            return "timestamp"
        case "timestamp with time zone" | "timestamptz":
            return "timestamptz"
        case "interval":
            return "interval"
        case _:
            # User-defined enums show up as the type name; treat as enum if pg_type.typtype = 'e'
            # but we don't have that here cheaply — fall back to "unknown" (the recipe layer can override).
            return "unknown"


def introspect(engine: Engine) -> Schema:
    started = time.monotonic()
    insp = inspect(engine)
    with engine.connect() as conn:
        server_version = conn.execute(text("SHOW server_version")).scalar_one()

        all_schemas = [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]
        log.info("introspect: server=%s schemas=%s", server_version, all_schemas)

        tables: list[Table] = []
        views: list[View] = []

        # Bulk-fetch row count estimates for all tables (cheap; uses pg_class.reltuples)
        reltuples_rows = conn.execute(
            text(
                """
                SELECT n.nspname AS schema, c.relname AS name, c.reltuples::bigint AS rows
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r' AND n.nspname = ANY(:schemas)
                """
            ),
            {"schemas": list(all_schemas)},
        ).all()
        row_estimates = {(r.schema, r.name): int(r.rows) for r in reltuples_rows}

        # Bulk-fetch RLS-enabled flag
        rls_rows = conn.execute(
            text(
                """
                SELECT n.nspname AS schema, c.relname AS name, c.relrowsecurity AS rls
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r' AND n.nspname = ANY(:schemas)
                """
            ),
            {"schemas": list(all_schemas)},
        ).all()
        rls_enabled = {(r.schema, r.name): bool(r.rls) for r in rls_rows}

        for schema_name in all_schemas:
            table_names = insp.get_table_names(schema=schema_name)
            view_names = insp.get_view_names(schema=schema_name)
            log.info(
                "introspect: schema=%s tables=%d views=%d", schema_name, len(table_names), len(view_names)
            )
            for i, table_name in enumerate(table_names, start=1):
                t0 = time.monotonic()
                cols = _columns(insp, schema_name, table_name)
                idxs = _indexes(insp, schema_name, table_name)
                tables.append(
                    Table(
                        schema=schema_name,
                        name=table_name,
                        columns=cols,
                        indexes=idxs,
                        row_count_estimate=row_estimates.get((schema_name, table_name)),
                        rls_enabled=rls_enabled.get((schema_name, table_name), False),
                    )
                )
                if i % 10 == 0 or i == len(table_names):
                    log.info(
                        "introspect: %s table %d/%d (%s) %.2fs",
                        schema_name, i, len(table_names), table_name, time.monotonic() - t0,
                    )

            for j, view_name in enumerate(view_names, start=1):
                definition = insp.get_view_definition(view_name, schema=schema_name) or ""
                views.append(View(schema=schema_name, name=view_name, definition=definition))
                if j % 10 == 0 or j == len(view_names):
                    log.info("introspect: %s view %d/%d (%s)", schema_name, j, len(view_names), view_name)

        extensions = [
            r.extname for r in conn.execute(text("SELECT extname FROM pg_extension ORDER BY extname")).all()
        ]

        rls_policies = [
            RlsPolicy(
                schema=r.schemaname,
                table=r.tablename,
                name=r.policyname,
                command=r.cmd,
                using_expr=r.qual,
                with_check_expr=r.with_check,
                permissive=(r.permissive == "PERMISSIVE"),
            )
            for r in conn.execute(
                text(
                    """
                    SELECT schemaname, tablename, policyname, cmd, qual, with_check, permissive
                    FROM pg_policies
                    WHERE schemaname = ANY(:schemas)
                    """
                ),
                {"schemas": list(all_schemas)},
            ).all()
        ]

    log.info(
        "introspect: done in %.2fs (%d tables, %d views, %d rls policies)",
        time.monotonic() - started, len(tables), len(views), len(rls_policies),
    )
    return Schema(
        engine="postgres",
        server_version=str(server_version),
        tables=tables,
        views=views,
        extensions=extensions,
        rls_policies=rls_policies,
    )


def _columns(insp, schema: str, table: str) -> list[Column]:
    pk_cols = set(insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or [])
    fks = {
        c: ForeignKeyRef(
            schema=fk.get("referred_schema") or "public",
            table=fk["referred_table"],
            column=fk["referred_columns"][0],
        )
        for fk in insp.get_foreign_keys(table, schema=schema)
        for c in fk["constrained_columns"]
    }

    cols: list[Column] = []
    for col in insp.get_columns(table, schema=schema):
        native = str(col["type"])
        cols.append(
            Column(
                name=col["name"],
                native_type=native,
                normalized_type=_normalize_type(native),
                nullable=bool(col.get("nullable", True)),
                default=str(col["default"]) if col.get("default") is not None else None,
                is_primary_key=col["name"] in pk_cols,
                foreign_key=fks.get(col["name"]),
            )
        )
    return cols


def _indexes(insp, schema: str, table: str) -> list[Index]:
    """Build Index models from SQLAlchemy's inspector output.

    Postgres expression indexes (e.g. `CREATE INDEX ON t (lower(name))`) come back from
    SQLAlchemy with `None` entries in `column_names` — the actual expression sits in a
    parallel `expressions` key (psycopg dialect). We substitute the expression text in
    parentheses so the schema model stays `list[str]` and downstream code doesn't have
    to special-case nulls.
    """
    out: list[Index] = []
    for idx in insp.get_indexes(table, schema=schema):
        if not idx.get("name"):
            continue
        col_names = idx.get("column_names") or []
        expressions = idx.get("expressions") or []
        cols: list[str] = []
        for i, col in enumerate(col_names):
            if col is not None:
                cols.append(col)
            elif i < len(expressions) and expressions[i]:
                cols.append(f"({expressions[i]})")
            else:
                cols.append("(expression)")
        out.append(Index(name=idx["name"], columns=cols, unique=bool(idx.get("unique"))))
    return out
