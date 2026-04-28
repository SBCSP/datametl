"""End-to-end migration runner.

Reads a `MigrationRun` from the metadata DB, resolves its plan, opens connections to source
and destination, runs each included table through the strategy, then runs verification.
Updates the run rows + per-table rows as it goes so the UI can poll progress.

Top-level rule: write nothing to the user's databases unless this runner did it. The
strategy is the only thing that issues writes, and it scopes everything to a single
destination transaction per table (committed after a successful COPY + post-checks).

FK handling: we set `session_replication_role = replica` on the destination for the
duration of the run so FKs don't fire during the load. That session is per-connection;
the strategy's destination connection inherits it, then we reset on shutdown.
"""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.connectors.postgres import PostgresConnector
from app.crypto import vault
from app.introspection.normalized import Schema as NormalizedSchema
from app.migrations.planner import MigrationPlan, build_plan, TableOptionsPayload
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.mapping import Mapping
from app.models.migration_run import MigrationRun, MigrationRunStatus
from app.models.migration_run_table import (
    ConflictMode,
    MigrationRunTable,
    TableRunStatus,
)
from app.models.schema_snapshot import SchemaSnapshot
from app.strategies.logical_copy import LogicalCopyStrategy
from app.strategies.base import TableMoveContext
from app.transforms.column_plan import build_column_plan
from app.verification import CheckContext, run_checks

log = logging.getLogger("datametl.migration.runner")


def create_run(
    db: Session,
    *,
    comparison_id: uuid.UUID,
    options: TableOptionsPayload,
) -> MigrationRun:
    """Persist a new MigrationRun + one MigrationRunTable per included table.

    Called from the API. The actual execution happens later in `execute_run`, normally
    triggered by the arq worker.
    """
    cmp = db.get(Comparison, comparison_id)
    if cmp is None:
        raise ValueError(f"Unknown comparison: {comparison_id}")
    src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
    if src_snap is None:
        raise ValueError("Comparison source snapshot missing")

    src_schema_obj = NormalizedSchema.model_validate(src_snap.normalized_schema)
    plan = build_plan(cmp, options, src_schema_obj)

    run = MigrationRun(
        comparison_id=cmp.id,
        status=MigrationRunStatus.pending,
        plan=plan.to_jsonable(),
    )
    db.add(run)
    db.flush()

    for pt in plan.included:
        db.add(
            MigrationRunTable(
                run_id=run.id,
                source_table=pt.source_table,
                dest_table=pt.dest_table,
                conflict_mode=pt.conflict_mode,
                status=TableRunStatus.pending,
            )
        )

    db.commit()
    db.refresh(run)
    return run


def execute_run(db: Session, run_id: uuid.UUID) -> dict:
    """Execute a previously-persisted MigrationRun. Idempotent only in the sense that
    re-running TRUNCATEs the destination first; multiple concurrent calls are not safe."""
    run = db.get(MigrationRun, run_id)
    if run is None:
        raise ValueError(f"Unknown run: {run_id}")

    cmp = db.get(Comparison, run.comparison_id)
    if cmp is None:
        raise ValueError("Run references missing comparison")
    src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
    dst_snap = db.get(SchemaSnapshot, cmp.dest_snapshot_id)
    if src_snap is None or dst_snap is None:
        raise ValueError("Run references missing snapshots")
    src_conn = db.get(Connection, src_snap.connection_id)
    dst_conn = db.get(Connection, dst_snap.connection_id)
    if src_conn is None or dst_conn is None:
        raise ValueError("Run references missing connections")

    # Mark run as running.
    run.status = MigrationRunStatus.running
    run.started_at = datetime.now(tz=timezone.utc)
    db.commit()

    src_creds = vault.decrypt(src_conn.encrypted_credentials)
    dst_creds = vault.decrypt(dst_conn.encrypted_credentials)
    src_engine = PostgresConnector(src_creds)._engine()
    dst_engine = PostgresConnector(dst_creds)._engine()

    # FK deferral on destination — set on every new connection that comes out of the pool
    # for the duration of this run. The strategy and verification both use connections from
    # this engine, so they all inherit it (psycopg defaults to one connection per checkout).
    @_event_listens_for(dst_engine, "connect")
    def _fk_defer(dbapi_conn, _connection_record):  # type: ignore[no-redef]
        with dbapi_conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")

    strategy = LogicalCopyStrategy()
    plan_tables = list(
        db.query(MigrationRunTable).filter(MigrationRunTable.run_id == run.id).all()
    )

    overall_error: str | None = None
    succeeded = 0
    failed = 0

    # Sort tables by FK dependency to load parents before children.
    plan_tables = _topo_sort(plan_tables, src_engine)

    for prt in plan_tables:
        try:
            _run_table(
                db, run=run, prt=prt,
                src_engine=src_engine, dst_engine=dst_engine,
                strategy=strategy,
            )
            if prt.status == TableRunStatus.succeeded:
                succeeded += 1
            else:
                failed += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            overall_error = overall_error or str(e)
            prt.status = TableRunStatus.failed
            prt.error = traceback.format_exc()
            prt.finished_at = datetime.now(tz=timezone.utc)
            db.commit()

    # Final status.
    run.finished_at = datetime.now(tz=timezone.utc)
    if failed == 0:
        run.status = MigrationRunStatus.succeeded
    else:
        run.status = MigrationRunStatus.failed
        run.error = overall_error or f"{failed} table(s) failed"
    db.commit()

    return {
        "run_id": str(run.id),
        "status": run.status.value,
        "succeeded": succeeded,
        "failed": failed,
    }


def _run_table(
    db: Session,
    *,
    run: MigrationRun,
    prt: MigrationRunTable,
    src_engine,
    dst_engine,
    strategy: LogicalCopyStrategy,
) -> None:
    log.info("run %s: starting %s → %s", run.id, prt.source_table, prt.dest_table)
    prt.status = TableRunStatus.running
    prt.started_at = datetime.now(tz=timezone.utc)
    db.commit()

    # Resolve mappings for this (src_table, dst_table) pair.
    mappings = (
        db.query(Mapping)
        .filter(
            Mapping.comparison_id == run.comparison_id,
            Mapping.source_table == prt.source_table,
            Mapping.dest_table == prt.dest_table,
        )
        .order_by(Mapping.source_column)
        .all()
    )
    if not mappings:
        raise RuntimeError(f"No mappings found for {prt.source_table} → {prt.dest_table}")

    column_plan = build_column_plan(mappings)
    if not column_plan.dest_columns:
        raise RuntimeError("Column plan has no columns — every mapping is skipped?")

    ctx = TableMoveContext(
        source_table=prt.source_table,
        dest_table=prt.dest_table,
        column_plan=column_plan,
        conflict_mode=prt.conflict_mode.value if isinstance(prt.conflict_mode, ConflictMode) else prt.conflict_mode,
    )

    t0 = time.monotonic()
    move = strategy.run(src_engine, dst_engine, ctx)
    log.info(
        "run %s: %s rows_read=%d rows_written=%d duration_ms=%d",
        run.id, prt.source_table, move.rows_read, move.rows_written, move.duration_ms,
    )

    prt.rows_read = move.rows_read
    prt.rows_written = move.rows_written
    prt.duration_ms = move.duration_ms

    # Verification — find the level on the run.plan for this table.
    level = _verification_level_for(run, prt)
    check_results = run_checks(
        src_engine, dst_engine,
        level=level,
        ctx=CheckContext(source_table=prt.source_table, dest_table=prt.dest_table),
    )
    prt.verification = [r.as_dict() for r in check_results]

    if any(not r.passed for r in check_results):
        prt.status = TableRunStatus.failed
        prt.error = "; ".join(f"{r.name}: {r.detail}" for r in check_results if not r.passed)
    else:
        prt.status = TableRunStatus.succeeded

    prt.finished_at = datetime.now(tz=timezone.utc)
    db.commit()
    log.info("run %s: %s → %s in %.2fs", run.id, prt.status.value, prt.dest_table, time.monotonic() - t0)


def _verification_level_for(run: MigrationRun, prt: MigrationRunTable) -> str:
    plan = run.plan or {}
    for entry in plan.get("included", []):
        if entry.get("source_table") == prt.source_table and entry.get("dest_table") == prt.dest_table:
            return entry.get("verification") or "count_and_sample"
    return "count_and_sample"


def _topo_sort(tables: list[MigrationRunTable], src_engine) -> list[MigrationRunTable]:
    """Order tables so each table's FK targets come first.

    For v1: cheap to compute from the source's information_schema. If a cycle is detected,
    we fall back to the original order — the runner already sets session_replication_role
    on the destination so FKs don't enforce mid-load.
    """
    qualified = {(prt.source_table) for prt in tables}
    deps: dict[str, set[str]] = {prt.source_table: set() for prt in tables}

    try:
        with src_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT
                        tc.table_schema || '.' || tc.table_name AS child,
                        ccu.table_schema || '.' || ccu.table_name AS parent
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                     AND tc.table_schema = ccu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    """
                )
            ).all()
            for r in rows:
                if r.child in deps and r.parent in qualified and r.child != r.parent:
                    deps[r.child].add(r.parent)
    except Exception:  # noqa: BLE001
        log.warning("topo_sort: failed to load FK dependencies; using input order", exc_info=True)
        return tables

    # Kahn's algorithm
    by_name = {prt.source_table: prt for prt in tables}
    out: list[MigrationRunTable] = []
    no_dep = [n for n, d in deps.items() if not d]
    visited: set[str] = set()
    while no_dep:
        n = no_dep.pop(0)
        if n in visited:
            continue
        visited.add(n)
        out.append(by_name[n])
        for child, parents in deps.items():
            if n in parents:
                parents.discard(n)
                if not parents and child not in visited:
                    no_dep.append(child)

    if len(out) != len(tables):
        # Cycle — append remaining in input order.
        for prt in tables:
            if prt.source_table not in visited:
                out.append(prt)
    return out


def _event_listens_for(target, identifier):
    """Tiny indirection so the import is local — keeps top of file uncluttered."""
    from sqlalchemy import event
    return event.listens_for(target, identifier)
