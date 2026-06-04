from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    CronPreviewRequest,
    CronPreviewResponse,
    JobEnqueued,
    ScheduleCreate,
    ScheduledRunRead,
    ScheduleRead,
    ScheduleUpdate,
)
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.connection import Connection
from app.models.scheduled_script import ScheduledRun, ScheduledScript
from app.models.sql_script import SqlScript
from app.scheduling.cron import CronError, next_run, preview

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _to_read(db: Session, sched: ScheduledScript) -> ScheduleRead:
    script = db.get(SqlScript, sched.script_id)
    return ScheduleRead(
        id=sched.id,
        name=sched.name,
        script_id=sched.script_id,
        script_name=script.name if script else None,
        connection_ids=[uuid.UUID(c) for c in sched.connection_ids],
        cron=sched.cron,
        timezone=sched.timezone,
        allow_writes=sched.allow_writes,
        enabled=sched.enabled,
        last_run_at=sched.last_run_at,
        next_run_at=sched.next_run_at,
        created_at=sched.created_at,
        updated_at=sched.updated_at,
    )


def _require_script(db: Session, script_id: uuid.UUID) -> SqlScript:
    script = db.get(SqlScript, script_id)
    if script is None:
        raise HTTPException(404, "Script not found")
    return script


def _validate_connections(db: Session, connection_ids: list[uuid.UUID]) -> None:
    existing = set(
        db.execute(select(Connection.id).where(Connection.id.in_(connection_ids))).scalars()
    )
    missing = [str(cid) for cid in connection_ids if cid not in existing]
    if missing:
        raise HTTPException(404, f"Unknown connection(s): {', '.join(missing)}")


@router.get("", response_model=list[ScheduleRead])
def list_schedules(db: Session = Depends(get_db)) -> list[ScheduleRead]:
    rows = db.execute(
        select(ScheduledScript).order_by(ScheduledScript.created_at.desc())
    ).scalars()
    return [_to_read(db, s) for s in rows]


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(payload: ScheduleCreate, db: Session = Depends(get_db)) -> ScheduleRead:
    script = _require_script(db, payload.script_id)
    _validate_connections(db, payload.connection_ids)
    try:
        upcoming = next_run(payload.cron, payload.timezone)
    except CronError as e:
        raise HTTPException(422, str(e)) from e

    sched = ScheduledScript(
        name=(payload.name or script.name).strip() or script.name,
        script_id=payload.script_id,
        connection_ids=[str(c) for c in payload.connection_ids],
        cron=payload.cron,
        timezone=payload.timezone,
        allow_writes=payload.allow_writes,
        enabled=payload.enabled,
        next_run_at=upcoming if payload.enabled else None,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return _to_read(db, sched)


@router.get("/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: uuid.UUID, db: Session = Depends(get_db)) -> ScheduleRead:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    return _to_read(db, sched)


@router.put("/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: uuid.UUID, payload: ScheduleUpdate, db: Session = Depends(get_db)
) -> ScheduleRead:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")

    if payload.script_id is not None:
        _require_script(db, payload.script_id)
        sched.script_id = payload.script_id
    if payload.connection_ids is not None:
        _validate_connections(db, payload.connection_ids)
        sched.connection_ids = [str(c) for c in payload.connection_ids]
    if payload.name is not None:
        sched.name = payload.name.strip() or sched.name
    if payload.cron is not None:
        sched.cron = payload.cron
    if payload.timezone is not None:
        sched.timezone = payload.timezone
    if payload.allow_writes is not None:
        sched.allow_writes = payload.allow_writes
    if payload.enabled is not None:
        sched.enabled = payload.enabled

    # Recompute the next fire time whenever cron/timezone/enabled change (or anything, to be
    # safe — it's cheap). A disabled schedule has no next run.
    if sched.enabled:
        try:
            sched.next_run_at = next_run(sched.cron, sched.timezone)
        except CronError as e:
            raise HTTPException(422, str(e)) from e
    else:
        sched.next_run_at = None

    db.commit()
    db.refresh(sched)
    return _to_read(db, sched)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    db.delete(sched)
    db.commit()


@router.post("/{schedule_id}/run-now", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def run_schedule_now(schedule_id: uuid.UUID, db: Session = Depends(get_db)) -> JobEnqueued:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    job_id = await enqueue("run_scheduled_script", str(schedule_id))
    return JobEnqueued(job_id=job_id)


@router.get("/{schedule_id}/runs", response_model=list[ScheduledRunRead])
def list_schedule_runs(
    schedule_id: uuid.UUID, limit: int = 25, db: Session = Depends(get_db)
) -> list[ScheduledRun]:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    return list(
        db.execute(
            select(ScheduledRun)
            .where(ScheduledRun.schedule_id == schedule_id)
            .order_by(ScheduledRun.started_at.desc())
            .limit(max(1, min(limit, 200)))
        ).scalars()
    )


@router.post("/preview", response_model=CronPreviewResponse)
def preview_cron(payload: CronPreviewRequest) -> CronPreviewResponse:
    try:
        runs = preview(payload.cron, payload.timezone, n=3, after=datetime.now(UTC))
    except CronError as e:
        return CronPreviewResponse(valid=False, error=str(e), next_runs=[])
    return CronPreviewResponse(valid=True, next_runs=runs)
