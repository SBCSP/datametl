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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from app.comparison import diff_schemas
from app.connectors import for_engine
from app.crypto import vault
from app.db import SessionLocal
from app.introspection.normalized import Schema
from app.mapping import seed_mappings_for_comparison
from app.migrations.runner import execute_run as execute_migration_run
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.scheduled_script import ScheduledRun, ScheduledScript
from app.models.schema_snapshot import SchemaSnapshot
from app.models.sql_script import SqlScript
from app.recipes.supabase import analyze as analyze_supabase
from app.scheduling.cron import next_run as cron_next_run
from app.scripts.exec_core import run_against_connections
from app.scripts.runner import split_statements
from app.verification_runs.runner import execute_run as execute_verification_run


def _load_connections(db: Any, connection_ids: list[str]) -> list[dict[str, Any]]:
    """Decrypt the chosen connections into plain dicts for the execution core.

    A missing connection (deleted between save and run) becomes a marker dict so it surfaces
    as one failed entry instead of aborting the run."""
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
    return conns


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


async def run_pipeline(ctx: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Execute a previously-created PipelineRun. The steps are sync (psycopg COPY / SQL), so
    offload to a thread like the migration runner."""
    from app.etl.runner import execute_pipeline_run

    run_uuid = uuid.UUID(run_id)

    def _run() -> dict[str, Any]:
        with SessionLocal() as db:
            return execute_pipeline_run(db, run_uuid)

    return await asyncio.to_thread(_run)


async def execute_sql_script(
    ctx: dict[str, Any], script_id: str, connection_ids: list[str], read_only: bool = True
) -> dict[str, Any]:
    """Run a saved SQL script against each selected connection and collect results.

    Each connection runs in its own thread (the SQL is sync, like introspect) and is fully
    isolated: a connection that can't connect or hits an error becomes a failed entry in the
    output rather than failing the whole run. When `read_only` (the default) every statement
    runs in a read-only transaction that is rolled back; when False, writes are allowed and the
    script commits atomically per connection (see PostgresConnector.run_statements).
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

        # Record this run (atomic increment + last-run stamp) so /scripts can show usage.
        db.execute(
            update(SqlScript)
            .where(SqlScript.id == script_uuid)
            .values(run_count=SqlScript.run_count + 1, last_run_at=func.now())
        )
        db.commit()

        conns = _load_connections(db, connection_ids)

    results = await run_against_connections(conns, statements, read_only)
    return {
        "script_id": script_id,
        "statement_count": len(statements),
        "connections": results,
    }


def _summarize_connection(conn_result: dict[str, Any]) -> dict[str, Any]:
    """Compact a full per-connection result down to what scheduled-run history stores:
    name + ok + first error + total rows across all statements (no result rows)."""
    statements = conn_result.get("statements") or []
    row_total = sum(int(s.get("row_count") or 0) for s in statements)
    error = conn_result.get("error")
    if error is None:
        first_err = next((s.get("error") for s in statements if s.get("error")), None)
        error = first_err
    return {
        "connection_name": conn_result.get("connection_name"),
        "ok": bool(conn_result.get("ok")),
        "error": error,
        "row_total": row_total,
    }


async def dispatch_due_schedules(ctx: dict[str, Any]) -> dict[str, Any]:
    """Arq cron entrypoint (runs every minute): enqueue any enabled schedule that is due.

    For each due schedule we advance `next_run_at` to the next future occurrence *before*
    enqueuing, so a worker that was down for a while fires each schedule at most once on
    recovery instead of replaying every missed minute. The actual run happens in
    `run_scheduled_script`.
    """
    from app.jobs.queue import enqueue  # local import avoids a cycle at module load

    now = datetime.now(UTC)
    due_ids: list[str] = []
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(ScheduledScript).where(
                    ScheduledScript.enabled.is_(True),
                    ScheduledScript.next_run_at.is_not(None),
                    ScheduledScript.next_run_at <= now,
                )
            ).scalars()
        )
        for sched in rows:
            try:
                upcoming = cron_next_run(sched.cron, sched.timezone, after=now)
            except Exception:
                # A malformed cron/tz shouldn't wedge the dispatcher; disable it so it stops
                # matching and the user can fix it.
                sched.enabled = False
                continue
            sched.last_run_at = now
            sched.next_run_at = upcoming
            due_ids.append(str(sched.id))
        db.commit()

    for sid in due_ids:
        await enqueue("run_scheduled_script", sid)
    return {"dispatched": len(due_ids)}


async def run_scheduled_script(ctx: dict[str, Any], schedule_id: str) -> dict[str, Any]:
    """Execute one scheduled script run and persist a compact history record.

    Reuses the same execution core as the manual runner (read-only unless the schedule opts
    into writes). A `ScheduledRun` row is created up front (status=running) and finalized with
    a per-connection summary so the UI can show what each overnight run did.
    """
    sched_uuid = uuid.UUID(schedule_id)

    with SessionLocal() as db:
        sched = db.get(ScheduledScript, sched_uuid)
        if sched is None:
            raise ValueError(f"Unknown schedule: {schedule_id}")
        script = db.get(SqlScript, sched.script_id)
        if script is None:
            raise ValueError(f"Schedule {schedule_id} references a missing script")
        statements = split_statements(script.content)
        read_only = not sched.allow_writes
        connection_ids = [str(c) for c in sched.connection_ids]

        run = ScheduledRun(schedule_id=sched.id, status="running", summary=[])
        db.add(run)

        # A scheduled run counts as a run of the underlying script.
        db.execute(
            update(SqlScript)
            .where(SqlScript.id == sched.script_id)
            .values(run_count=SqlScript.run_count + 1, last_run_at=func.now())
        )
        db.commit()
        run_id = run.id
        conns = _load_connections(db, connection_ids)

    error: str | None = None
    summary: list[dict[str, Any]] = []
    try:
        results = await run_against_connections(conns, statements, read_only)
        summary = [_summarize_connection(r) for r in results]
        oks = [s["ok"] for s in summary]
        if all(oks):
            status_str = "succeeded"
        elif any(oks):
            status_str = "partial"
        else:
            status_str = "failed"
    except Exception as e:  # whole-run failure (should be rare; per-conn errors are isolated)
        status_str = "failed"
        error = str(getattr(e, "__cause__", None) or e)

    with SessionLocal() as db:
        db.execute(
            update(ScheduledRun)
            .where(ScheduledRun.id == run_id)
            .values(status=status_str, summary=summary, error=error, finished_at=func.now())
        )
        db.commit()

    return {"schedule_id": schedule_id, "run_id": str(run_id), "status": status_str}
