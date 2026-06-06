"""Lightweight "apply a snapshot's schema to a fresh database".

Builds CREATE-DDL from a normalized snapshot (reusing app/migrations/ddl.py for the per-table
SQL) and executes it against a chosen destination. This is a DELIBERATE, user-initiated action
(distinct from the migration runner, which never auto-creates) — it only runs when the operator
picks a target and clicks Apply.

Scope (lightweight, Phase 1): extensions, CREATE SCHEMA for non-public schemas, CREATE TABLE
(columns/types/defaults/NOT NULL/PK), indexes, and single-column FOREIGN KEY constraints.

Known gaps (deferred to a pg_dump-grade Phase 2): views, RLS policies, triggers, functions,
enums / custom types, composite FKs, sequence ownership, grants, comments. For an exact clone,
pg_dump --schema-only is the right tool.

Execution is per-statement and continue-on-error: each statement runs in its own transaction so
one failure (e.g. an unavailable extension, or an FK to a schema you didn't include) is reported
without rolling back everything else.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.introspection.normalized import Schema, Table
from app.migrations.ddl import create_index_sql, create_table_sql


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _fk_statements(table: Table, schema_override: str | None) -> list[str]:
    """Single-column FK constraints for a table, emitted as ALTER TABLE ADD CONSTRAINT so they
    can run after every table exists (creation order then doesn't matter)."""
    out: list[str] = []
    child_schema = schema_override or table.schema_
    for col in table.columns:
        fk = col.foreign_key
        if fk is None:
            continue
        ref_schema = schema_override or fk.schema_
        name = f"{table.name}_{col.name}_fkey"
        out.append(
            f"ALTER TABLE {_q(child_schema)}.{_q(table.name)} "
            f"ADD CONSTRAINT {_q(name)} FOREIGN KEY ({_q(col.name)}) "
            f"REFERENCES {_q(ref_schema)}.{_q(fk.table)} ({_q(fk.column)});"
        )
    return out


def build_ddl_statements(schema: Schema, *, schema_override: str | None = None) -> list[str]:
    """Ordered DDL to stand up the snapshot's structure on a fresh database."""
    statements: list[str] = []

    # 1. Extensions (IF NOT EXISTS — unavailable ones simply fail and are reported).
    for ext in schema.extensions:
        statements.append(f"CREATE EXTENSION IF NOT EXISTS {_q(ext)};")

    # 2. Schemas (non-public). When an override collapses everything into one schema, create it.
    if schema_override:
        target_schemas = {schema_override}
    else:
        target_schemas = {t.schema_ for t in schema.tables}
    for s in sorted(target_schemas):
        if s and s != "public":
            statements.append(f"CREATE SCHEMA IF NOT EXISTS {_q(s)};")

    # 3. Tables (CREATE TABLE includes PK). FK constraints are deferred to step 5.
    for t in schema.tables:
        statements.append(create_table_sql(t, schema_override=schema_override))

    # 4. Indexes (non-PK).
    for t in schema.tables:
        statements.extend(create_index_sql(t, schema_override=schema_override))

    # 5. Foreign keys (after all tables exist).
    for t in schema.tables:
        statements.extend(_fk_statements(t, schema_override))

    return statements


def build_ddl_text(schema: Schema, *, schema_override: str | None = None) -> str:
    return "\n\n".join(build_ddl_statements(schema, schema_override=schema_override))


def apply_ddl(creds: dict[str, Any], statements: list[str]) -> list[dict[str, Any]]:
    """Run each statement in its own transaction against the target, continuing past failures.

    Returns one result dict per statement: {index, sql, ok, error, duration_ms}."""
    from app.connectors.postgres import PostgresConnector  # local import keeps the module light

    engine = PostgresConnector(creds)._engine()
    results: list[dict[str, Any]] = []
    try:
        for i, stmt in enumerate(statements):
            started = time.perf_counter()
            try:
                with engine.begin() as conn:
                    conn.execute(text(stmt))
                results.append({
                    "index": i, "sql": stmt, "ok": True, "error": None,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                })
            except SQLAlchemyError as e:
                results.append({
                    "index": i, "sql": stmt, "ok": False, "error": str(e.__cause__ or e),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                })
    finally:
        engine.dispose()
    return results
