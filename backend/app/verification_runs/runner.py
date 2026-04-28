"""Orchestrate a standalone VerificationRun.

Per-table:
  1. Mark VerificationRunTable as running
  2. Run the configured checks via app.verification.run_checks
  3. Persist results, derive pass/fail status

Both connections are opened in `SET TRANSACTION READ ONLY` to make the read-only invariant
explicit at the DB level — even if a check class were buggy and tried to write, Postgres
would reject it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.connectors.postgres import PostgresConnector
from app.crypto import vault
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.schema_snapshot import SchemaSnapshot
from app.models.verification_run import VerificationRun, VerificationRunStatus
from app.models.verification_run_table import VerificationRunTable, VerificationTableStatus
from app.verification import CheckContext, run_checks

log = logging.getLogger("datametl.verification.runner")


def create_run(
    db: Session,
    *,
    comparison_id: uuid.UUID,
    options: dict,
) -> VerificationRun:
    """Persist a VerificationRun + per-table rows. Caller enqueues the worker job after."""
    cmp = db.get(Comparison, comparison_id)
    if cmp is None:
        raise ValueError(f"Unknown comparison: {comparison_id}")

    included = [t for t in options.get("tables", []) if t.get("include", True)]
    if not included:
        raise ValueError("No tables selected for verification")

    run = VerificationRun(
        comparison_id=cmp.id,
        status=VerificationRunStatus.pending,
        plan=options,
    )
    db.add(run)
    db.flush()

    default_level = options.get("default_level", "count_and_sample")
    for t in included:
        db.add(
            VerificationRunTable(
                run_id=run.id,
                source_table=t["source_table"],
                dest_table=t["dest_table"],
                level=t.get("level") or default_level,
            )
        )

    db.commit()
    db.refresh(run)
    return run


def execute_run(db: Session, run_id: uuid.UUID) -> dict:
    run = db.get(VerificationRun, run_id)
    if run is None:
        raise ValueError(f"Unknown verification run: {run_id}")

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

    run.status = VerificationRunStatus.running
    run.started_at = datetime.now(tz=timezone.utc)
    db.commit()

    src_creds = vault.decrypt(src_conn.encrypted_credentials)
    dst_creds = vault.decrypt(dst_conn.encrypted_credentials)
    src_engine = PostgresConnector(src_creds)._engine()
    dst_engine = PostgresConnector(dst_creds)._engine()

    # Belt and suspenders: every checkout from these engines starts in read-only mode so
    # *nothing* this code runs can ever write to either user database.
    @event.listens_for(src_engine, "connect")
    def _src_ro(dbapi_conn, _record):  # noqa: ARG001
        with dbapi_conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")

    @event.listens_for(dst_engine, "connect")
    def _dst_ro(dbapi_conn, _record):  # noqa: ARG001
        with dbapi_conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")

    table_rows = (
        db.query(VerificationRunTable)
        .filter(VerificationRunTable.run_id == run.id)
        .order_by(VerificationRunTable.source_table)
        .all()
    )

    overall_pass = True
    error: str | None = None

    for vrt in table_rows:
        vrt.status = VerificationTableStatus.running
        vrt.started_at = datetime.now(tz=timezone.utc)
        db.commit()

        try:
            results = run_checks(
                src_engine,
                dst_engine,
                level=vrt.level,
                ctx=CheckContext(source_table=vrt.source_table, dest_table=vrt.dest_table),
            )
            vrt.results = [r.as_dict() for r in results]
            all_passed = all(r.passed for r in results)
            vrt.status = VerificationTableStatus.passed if all_passed else VerificationTableStatus.failed
            if not all_passed:
                overall_pass = False
                vrt.error = "; ".join(f"{r.name}: {r.detail}" for r in results if not r.passed)
        except Exception as e:  # noqa: BLE001
            vrt.status = VerificationTableStatus.failed
            vrt.error = str(e)
            vrt.results = []
            overall_pass = False
            error = error or str(e)
            log.exception("verification: %s → %s failed", vrt.source_table, vrt.dest_table)

        vrt.finished_at = datetime.now(tz=timezone.utc)
        db.commit()

    run.finished_at = datetime.now(tz=timezone.utc)
    run.status = VerificationRunStatus.succeeded if overall_pass else VerificationRunStatus.failed
    run.error = error
    db.commit()

    return {
        "run_id": str(run.id),
        "status": run.status.value,
        "overall_pass": overall_pass,
        "tables_checked": len(table_rows),
    }
