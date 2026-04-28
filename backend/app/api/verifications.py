from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    VerificationRunCreate,
    VerificationRunEnqueued,
    VerificationRunRead,
    VerificationRunSummary,
    VerificationRunTableRead,
)
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.comparison import Comparison
from app.models.verification_run import VerificationRun, VerificationRunStatus
from app.models.verification_run_table import VerificationRunTable, VerificationTableStatus
from app.verification_runs.runner import create_run

router = APIRouter(prefix="/api/verifications", tags=["verifications"])


@router.post("/runs", response_model=VerificationRunEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def create_verification_run(
    payload: VerificationRunCreate, db: Session = Depends(get_db)
) -> VerificationRunEnqueued:
    cmp = db.get(Comparison, payload.comparison_id)
    if cmp is None:
        raise HTTPException(404, "Comparison not found")
    try:
        run = create_run(db, comparison_id=cmp.id, options=payload.options.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job_id = await enqueue("run_verification", str(run.id))
    return VerificationRunEnqueued(run_id=run.id, job_id=job_id)


@router.get("/runs", response_model=list[VerificationRunSummary])
def list_runs(db: Session = Depends(get_db)) -> list[VerificationRunSummary]:
    rows = list(db.execute(select(VerificationRun).order_by(VerificationRun.created_at.desc())).scalars())
    out: list[VerificationRunSummary] = []
    for r in rows:
        tables = (
            db.query(VerificationRunTable)
            .filter(VerificationRunTable.run_id == r.id)
            .all()
        )
        passes = sum(1 for t in tables if t.status == VerificationTableStatus.passed)
        fails = sum(1 for t in tables if t.status == VerificationTableStatus.failed)
        out.append(
            VerificationRunSummary(
                id=r.id,
                comparison_id=r.comparison_id,
                status=r.status.value,
                started_at=r.started_at,
                finished_at=r.finished_at,
                table_count=len(tables),
                pass_count=passes,
                fail_count=fails,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/runs/{run_id}", response_model=VerificationRunRead)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> VerificationRunRead:
    r = db.get(VerificationRun, run_id)
    if r is None:
        raise HTTPException(404, "Verification run not found")
    tables = (
        db.query(VerificationRunTable)
        .filter(VerificationRunTable.run_id == r.id)
        .order_by(VerificationRunTable.source_table)
        .all()
    )
    return VerificationRunRead(
        id=r.id,
        comparison_id=r.comparison_id,
        status=r.status.value,
        plan=r.plan or {},
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        created_at=r.created_at,
        tables=[
            VerificationRunTableRead(
                id=t.id,
                source_table=t.source_table,
                dest_table=t.dest_table,
                level=t.level,
                status=t.status.value,
                results=t.results or [],
                error=t.error,
                started_at=t.started_at,
                finished_at=t.finished_at,
            )
            for t in tables
        ],
    )


@router.post("/runs/{run_id}/cancel", response_model=VerificationRunRead)
def cancel_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> VerificationRunRead:
    r = db.get(VerificationRun, run_id)
    if r is None:
        raise HTTPException(404, "Verification run not found")
    if r.status in (VerificationRunStatus.succeeded, VerificationRunStatus.failed, VerificationRunStatus.cancelled):
        return get_run(run_id, db)
    r.status = VerificationRunStatus.cancelled
    pending = (
        db.query(VerificationRunTable)
        .filter(VerificationRunTable.run_id == r.id, VerificationRunTable.status == VerificationTableStatus.pending)
        .all()
    )
    for t in pending:
        t.status = VerificationTableStatus.skipped
        t.error = "cancelled by user"
    db.commit()
    return get_run(run_id, db)
