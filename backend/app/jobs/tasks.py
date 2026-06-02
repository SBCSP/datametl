"""Long-running work runs in arq workers, not in HTTP request handlers.

Rationale: introspecting a large schema (hundreds of tables, RLS policies, view definitions)
can take many seconds. Same for diffing across two snapshots. Keep request handlers fast and
let the UI poll job status.

Concurrency note: arq runs multiple jobs in the same event loop. Any sync I/O (like our
SQLAlchemy-driven introspection) blocks the loop until it returns, which would queue all
other jobs sequentially. We offload the slow sync calls to a thread pool with
`asyncio.to_thread` so multiple introspects can actually run in parallel up to `max_jobs`.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.connectors import for_engine
from app.crypto import vault
from app.db import SessionLocal
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.schema_snapshot import SchemaSnapshot
from app.models.sql_script import SqlScript
from app.scripts.runner import ROW_CAP, STATEMENT_TIMEOUT_S, split_statements
from app.recipes.supabase import analyze as analyze_supabase
from app.comparison import diff_schemas
from app.mapping import seed_mappings_for_comparison
from app.introspection.normalized import Schema
from app.migrations.runner import execute_run as execute_migration_run
from app.verification_runs.runner import execute_run as execute_verification_run


async def introspect_connection(ctx: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Snapshot a connection's schema and persist it."""
    conn_uuid = uuid.UUID(connection_id)
    with SessionLocal() as db:
        conn = db.get(Connection, conn_uuid)
        if conn is None:
            raise ValueError(f"Unknown connection: {connection_id}")
        creds = vault.decrypt(conn.encrypted_credentials)
        connector = for_engine(conn.engine, creds)
        # Offload the blocking SQL to a thread so the event loop stays free for other jobs.
        schema = await asyncio.to_thread(connector.introspect)
        warnings = analyze_supabase(schema) if conn.engine == "postgres" else []

        snapshot = SchemaSnapshot(
            connection_id=conn.id,
            normalized_schema=schema.model_dump(by_alias=True, mode="json"),
            warnings=[w.model_dump(mode="json") for w in warnings],
        )
        db.add(snapshot)
        db.commit()
        return {"snapshot_id": str(snapshot.id), "warnings": len(warnings), "tables": len(schema.tables)}


async def run_comparison(ctx: dict[str, Any], comparison_id: str) -> dict[str, Any]:
    """Compute diff and seed default mappings for a comparison.

    Honors the comparison's optional schema scope: if both `source_schema` and
    `dest_schema` are set on the row, the diff and mapping seeding are restricted to
    those schemas (with cross-schema name matching).
    """
    cmp_uuid = uuid.UUID(comparison_id)
    with SessionLocal() as db:
        cmp = db.get(Comparison, cmp_uuid)
        if cmp is None:
            raise ValueError(f"Unknown comparison: {comparison_id}")
        src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
        dst_snap = db.get(SchemaSnapshot, cmp.dest_snapshot_id)
        assert src_snap and dst_snap

        src_full = Schema.model_validate(src_snap.normalized_schema)
        dst_full = Schema.model_validate(dst_snap.normalized_schema)

        diff = diff_schemas(
            src_full,
            dst_full,
            source_schema=cmp.source_schema,
            dest_schema=cmp.dest_schema,
        )
        cmp.diff = diff.model_dump(mode="json")

        inserted = seed_mappings_for_comparison(
            db,
            comparison_id=cmp.id,
            source=src_full,
            dest=dst_full,
            source_schema=cmp.source_schema,
            dest_schema=cmp.dest_schema,
        )
        db.commit()
        return {
            "comparison_id": str(cmp.id),
            "mappings_seeded": inserted,
            "source_schema": cmp.source_schema,
            "dest_schema": cmp.dest_schema,
        }


async def run_migration(ctx: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Execute a previously-created MigrationRun.

    The actual data movement is sync (psycopg COPY), so we offload to a thread to avoid
    blocking the arq event loop — same pattern as introspect_connection.
    """
    run_uuid = uuid.UUID(run_id)

    def _run() -> dict[str, Any]:
        with SessionLocal() as db:
            return execute_migration_run(db, run_uuid)

    return await asyncio.to_thread(_run)


async def run_verification(ctx: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Execute a standalone VerificationRun. Reads only — never writes to either user DB."""
    run_uuid = uuid.UUID(run_id)

    def _run() -> dict[str, Any]:
        with SessionLocal() as db:
            return execute_verification_run(db, run_uuid)

    return await asyncio.to_thread(_run)


async def execute_sql_script(
    ctx: dict[str, Any], script_id: str, connection_ids: list[str]
) -> dict[str, Any]:
    """Run a saved SQL script (read-only) against each selected connection and collect results.

    Each connection runs in its own thread (the SQL is sync, like introspect) and is fully
    isolated: a connection that can't connect or hits an error becomes a failed entry in the
    output rather than failing the whole run. Never writes — every statement executes inside a
    read-only transaction that is rolled back (see PostgresConnector.run_readonly_statements).
    """
    script_uuid = uuid.UUID(script_id)

    # Decrypt credentials while the metadata session is open, then hand plain dicts to the
    # worker threads. A missing connection (deleted between save and run) is kept as a marker
    # so it surfaces as one failed card instead of aborting the run.
    with SessionLocal() as db:
        script = db.get(SqlScript, script_uuid)
        if script is None:
            raise ValueError(f"Unknown script: {script_id}")
        statements = split_statements(script.content)

        conns: list[dict[str, Any]] = []
        for cid in (uuid.UUID(c) for c in connection_ids):
            conn = db.get(Connection, cid)
            if conn is None:
                conns.append({"id": str(cid), "name": "(deleted connection)", "engine": None, "creds": None})
            else:
                conns.append({
                    "id": str(conn.id),
                    "name": conn.name,
                    "engine": conn.engine,
                    "creds": vault.decrypt(conn.encrypted_credentials),
                })

    def _run_one(c: dict[str, Any]) -> dict[str, Any]:
        if c["engine"] is None:
            return {"connection_id": c["id"], "connection_name": c["name"], "ok": False,
                    "error": "Connection not found", "statements": []}
        try:
            connector = for_engine(c["engine"], c["creds"])
            stmts = connector.run_readonly_statements(statements, ROW_CAP, STATEMENT_TIMEOUT_S)
            ok = all(s["error"] is None for s in stmts)
            return {"connection_id": c["id"], "connection_name": c["name"], "ok": ok,
                    "error": None, "statements": stmts}
        except Exception as e:  # connection-level failure, isolate per connection
            # str(e.__cause__ or e) mirrors test_connection: surfaces the psycopg message
            # (host/port/db/user) without the password, which psycopg never includes.
            return {"connection_id": c["id"], "connection_name": c["name"], "ok": False,
                    "error": str(getattr(e, "__cause__", None) or e), "statements": []}

    results = await asyncio.gather(*[asyncio.to_thread(_run_one, c) for c in conns])
    return {
        "script_id": script_id,
        "statement_count": len(statements),
        "connections": list(results),
    }
