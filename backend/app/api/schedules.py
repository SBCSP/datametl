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
from app.models.tap import Tap, TapRun
from app.scheduling.cron import CronError, next_run, preview

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _to_read(db: Session, sched: ScheduledScript) -> ScheduleRead:
    script = db.get(SqlScript, sched.script_id) if sched.script_id else None
    tap = db.get(Tap, sched.tap_id) if sched.tap_id else None
    return ScheduleRead(
        id=sched.id,
        name=sched.name,
        target_kind=sched.target_kind,
        script_id=sched.script_id,
        script_name=script.name if script else None,
        connection_ids=[uuid.UUID(c) for c in sched.connection_ids],
        allow_writes=sched.allow_writes,
        tap_id=sched.tap_id,
        tap_name=tap.name if tap else None,
        tap_write_mode=sched.tap_write_mode,
        cron=sched.cron,
        timezone=sched.timezone,
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


def _require_tap(db: Session, tap_id: uuid.UUID) -> Tap:
    tap = db.get(Tap, tap_id)
    if tap is None:
        raise HTTPException(404, "Tap not found")
    return tap


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
    if payload.target_kind == "tap":
        if payload.tap_id is None:
            raise HTTPException(422, "tap_id is required for a tap schedule")
        if payload.tap_write_mode is None:
            raise HTTPException(422, "tap_write_mode is required for a tap schedule")
        default_name = _require_tap(db, payload.tap_id).name
    else:
        if payload.script_id is None:
            raise HTTPException(422, "script_id is required for a script schedule")
        if not payload.connection_ids:
            raise HTTPException(422, "Select at least one connection")
        _validate_connections(db, payload.connection_ids)
        default_name = _require_script(db, payload.script_id).name

    try:
        upcoming = next_run(payload.cron, payload.timezone)
    except CronError as e:
        raise HTTPException(422, str(e)) from e

    is_tap = payload.target_kind == "tap"
    sched = ScheduledScript(
        name=(payload.name or default_name).strip() or default_name,
        target_kind=payload.target_kind,
        script_id=None if is_tap else payload.script_id,
        connection_ids=[] if is_tap else [str(c) for c in payload.connection_ids],
        allow_writes=payload.allow_writes,
        tap_id=payload.tap_id if is_tap else None,
        tap_write_mode=payload.tap_write_mode if is_tap else None,
        cron=payload.cron,
        timezone=payload.timezone,
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

    if payload.target_kind is not None:
        sched.target_kind = payload.target_kind
    if payload.script_id is not None:
        _require_script(db, payload.script_id)
        sched.script_id = payload.script_id
    if payload.connection_ids is not None:
        _validate_connections(db, payload.connection_ids)
        sched.connection_ids = [str(c) for c in payload.connection_ids]
    if payload.tap_id is not None:
        _require_tap(db, payload.tap_id)
        sched.tap_id = payload.tap_id
    if payload.tap_write_mode is not None:
        sched.tap_write_mode = payload.tap_write_mode
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
    job = "run_scheduled_tap" if sched.target_kind == "tap" else "run_scheduled_script"
    job_id = await enqueue(job, str(schedule_id))
    return JobEnqueued(job_id=job_id)


@router.get("/{schedule_id}/runs", response_model=list[ScheduledRunRead])
def list_schedule_runs(
    schedule_id: uuid.UUID, limit: int = 25, db: Session = Depends(get_db)
) -> list[ScheduledRunRead]:
    sched = db.get(ScheduledScript, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    capped = max(1, min(limit, 200))

    # Tap schedules don't create ScheduledRun rows — the fetch's TapRun is the record. Adapt
    # the tap's recent fetches to the same shape so the History dialog works uniformly.
    if sched.target_kind == "tap":
        if sched.tap_id is None:
            return []
        tap_runs = db.execute(
            select(TapRun)
            .where(TapRun.tap_id == sched.tap_id)
            .order_by(TapRun.started_at.desc())
            .limit(capped)
        ).scalars()
        return [
            ScheduledRunRead(
                id=r.id,
                schedule_id=schedule_id,
                status=r.status,
                error=r.error,
                summary=r.summary,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in tap_runs
        ]

    return [
        ScheduledRunRead(
            id=r.id,
            schedule_id=r.schedule_id,
            status=r.status,
            error=r.error,
            summary=r.summary,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in db.execute(
            select(ScheduledRun)
            .where(ScheduledRun.schedule_id == schedule_id)
            .order_by(ScheduledRun.started_at.desc())
            .limit(capped)
        ).scalars()
    ]


@router.post("/preview", response_model=CronPreviewResponse)
def preview_cron(payload: CronPreviewRequest) -> CronPreviewResponse:
    try:
        runs = preview(payload.cron, payload.timezone, n=3, after=datetime.now(UTC))
    except CronError as e:
        return CronPreviewResponse(valid=False, error=str(e), next_runs=[])
    return CronPreviewResponse(valid=True, next_runs=runs)
