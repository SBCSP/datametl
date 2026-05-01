from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    MigrationOptionsPayload,
    MigrationPreflightRequest,
    MigrationPreflightResponse,
    MigrationRunCreate,
    MigrationRunEnqueued,
    MigrationRunRead,
    MigrationRunSummary,
    MigrationRunTableRead,
)
from app.db import get_db
from app.introspection.normalized import Schema as NormalizedSchema
from app.jobs.queue import enqueue
from app.migrations.planner import TableOption, TableOptionsPayload, build_plan
from app.migrations.pre_flight import run_preflight
from app.migrations.runner import create_run
from app.models.comparison import Comparison
from app.models.migration_run import MigrationRun, MigrationRunStatus
from app.models.migration_run_table import MigrationRunTable, TableRunStatus
from app.models.schema_snapshot import SchemaSnapshot

router = APIRouter(prefix="/api/migrations", tags=["migrations"])


def _to_planner(payload: MigrationOptionsPayload) -> TableOptionsPayload:
    """Convert API shape → planner shape (planner uses internal enums)."""
    return TableOptionsPayload(
        tables=[
            TableOption(
                source_table=t.source_table,
                dest_table=t.dest_table,
                include=t.include,
                conflict_mode=t.conflict_mode,  # type: ignore[arg-type]
                verification=t.verification,
            )
            for t in payload.tables
        ],
        default_verification=payload.default_verification,
    )


@router.post("/preflight", response_model=MigrationPreflightResponse)
def preflight(req: MigrationPreflightRequest, db: Session = Depends(get_db)) -> MigrationPreflightResponse:
    cmp = db.get(Comparison, req.comparison_id)
    if cmp is None:
        raise HTTPException(404, "Comparison not found")
    src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
    if src_snap is None:
        raise HTTPException(500, "Comparison source snapshot missing")

    src_schema_obj = NormalizedSchema.model_validate(src_snap.normalized_schema)
    plan = build_plan(cmp, _to_planner(req.options), src_schema_obj)
    result = run_preflight(db, plan=plan, comparison=cmp)

    return MigrationPreflightResponse(
        findings=[f.as_dict() for f in result.findings],
        can_run=result.can_run,
        would_truncate_counts=result.would_truncate_counts,
        skipped_tables=[
            {"source_table": s.source_table, "reason": s.reason, "ddl_preview": s.ddl_preview}
            for s in plan.skipped
        ],
    )


@router.post("/runs", response_model=MigrationRunEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def create_migration_run(
    req: MigrationRunCreate, db: Session = Depends(get_db)
) -> MigrationRunEnqueued:
    cmp = db.get(Comparison, req.comparison_id)
    if cmp is None:
        raise HTTPException(404, "Comparison not found")

    run = create_run(db, comparison_id=cmp.id, options=_to_planner(req.options))
    job_id = await enqueue("run_migration", str(run.id))
    return MigrationRunEnqueued(run_id=run.id, job_id=job_id)


@router.get("/runs", response_model=list[MigrationRunSummary])
def list_runs(db: Session = Depends(get_db)) -> list[MigrationRunSummary]:
    rows = db.execute(select(MigrationRun).order_by(MigrationRun.created_at.desc())).scalars()
    out: list[MigrationRunSummary] = []
    for r in rows:
        n = (
            db.query(MigrationRunTable)
            .filter(MigrationRunTable.run_id == r.id)
            .count()
        )
        out.append(
            MigrationRunSummary(
                id=r.id,
                comparison_id=r.comparison_id,
                status=r.status.value,
                started_at=r.started_at,
                finished_at=r.finished_at,
                table_count=n,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/runs/{run_id}", response_model=MigrationRunRead)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> MigrationRunRead:
    r = db.get(MigrationRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    tables = (
        db.query(MigrationRunTable)
        .filter(MigrationRunTable.run_id == r.id)
        .order_by(MigrationRunTable.source_table)
        .all()
    )
    return MigrationRunRead(
        id=r.id,
        comparison_id=r.comparison_id,
        status=r.status.value,
        plan=r.plan or {},
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        created_at=r.created_at,
        tables=[
            MigrationRunTableRead(
                id=t.id,
                source_table=t.source_table,
                dest_table=t.dest_table,
                conflict_mode=t.conflict_mode.value,
                status=t.status.value,
                rows_read=t.rows_read,
                rows_written=t.rows_written,
                duration_ms=t.duration_ms,
                verification=t.verification or [],
                error=t.error,
                started_at=t.started_at,
                finished_at=t.finished_at,
            )
            for t in tables
        ],
    )


@router.post("/runs/{run_id}/cancel", response_model=MigrationRunRead)
def cancel_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> MigrationRunRead:
    """Best-effort cancellation. arq doesn't support mid-task cancel for sync work, so this
    flips the run status to cancelled. The worker checks the run.status between tables and
    bails when it sees `cancelled`. A currently-running TRUNCATE/COPY will finish on its own
    and update its table row to succeeded/failed before the worker exits."""
    r = db.get(MigrationRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    if r.status in (MigrationRunStatus.succeeded, MigrationRunStatus.failed, MigrationRunStatus.cancelled):
        return get_run(run_id, db)
    r.status = MigrationRunStatus.cancelled
    # Mark any pending tables as skipped immediately; the runner will also do this on its
    # next iteration, but doing it here gives the UI a faster update.
    pending = (
        db.query(MigrationRunTable)
        .filter(MigrationRunTable.run_id == r.id, MigrationRunTable.status == TableRunStatus.pending)
        .all()
    )
    for t in pending:
        t.status = TableRunStatus.skipped
        t.error = "cancelled by user"
    db.commit()
    return get_run(run_id, db)


@router.post("/runs/{run_id}/cleanup-stale", response_model=MigrationRunRead)
def cleanup_stale_tables(run_id: uuid.UUID, db: Session = Depends(get_db)) -> MigrationRunRead:
    """Mark any tables stuck in 'running' or 'pending' as failed when the parent run has
    already terminated (succeeded / failed / cancelled). Useful when the worker died mid-run
    and didn't get a chance to write final per-table status, or when a cancellation left
    tables that were genuinely mid-COPY in a perpetual 'running' state in the UI."""
    r = db.get(MigrationRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    if r.status not in (MigrationRunStatus.succeeded, MigrationRunStatus.failed, MigrationRunStatus.cancelled):
        raise HTTPException(
            400,
            f"Run status is '{r.status.value}', not terminal — cancel first if you want "
            "to clean up tables stuck in 'running'.",
        )
    stale = (
        db.query(MigrationRunTable)
        .filter(
            MigrationRunTable.run_id == r.id,
            MigrationRunTable.status.in_([TableRunStatus.running, TableRunStatus.pending]),
        )
        .all()
    )
    for t in stale:
        t.status = TableRunStatus.failed
        t.error = (
            t.error
            or "stale: run terminated while this table was still in '%s' state. "
            "Re-run the migration to load this table." % t.status.value
        )
        if not t.finished_at:
            from datetime import datetime, timezone
            t.finished_at = datetime.now(tz=timezone.utc)
    db.commit()
    return get_run(run_id, db)
