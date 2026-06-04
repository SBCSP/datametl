from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    JobEnqueued,
    SqlScriptCreate,
    SqlScriptRead,
    SqlScriptRunRequest,
    SqlScriptUpdate,
)
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.connection import Connection
from app.models.scheduled_script import ScheduledRun, ScheduledScript
from app.models.sql_script import SqlScript

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.get("", response_model=list[SqlScriptRead])
def list_scripts(db: Session = Depends(get_db)) -> list[SqlScriptRead]:
    scripts = list(db.execute(select(SqlScript).order_by(SqlScript.updated_at.desc())).scalars())

    # Which scripts are scheduled, and is any schedule enabled? (one row per schedule)
    is_scheduled: dict[uuid.UUID, bool] = {}
    schedule_enabled: dict[uuid.UUID, bool] = {}
    for script_id, enabled in db.execute(
        select(ScheduledScript.script_id, ScheduledScript.enabled)
    ).all():
        is_scheduled[script_id] = True
        schedule_enabled[script_id] = schedule_enabled.get(script_id, False) or enabled

    # Latest scheduled-run status per script (DISTINCT ON keeps just the newest run).
    last_status: dict[uuid.UUID, str] = {}
    for script_id, run_status in db.execute(
        select(ScheduledScript.script_id, ScheduledRun.status)
        .join(ScheduledRun, ScheduledRun.schedule_id == ScheduledScript.id)
        .order_by(ScheduledScript.script_id, ScheduledRun.started_at.desc())
        .distinct(ScheduledScript.script_id)
    ).all():
        last_status[script_id] = run_status

    return [
        SqlScriptRead(
            id=s.id,
            name=s.name,
            content=s.content,
            description=s.description,
            run_count=s.run_count,
            last_run_at=s.last_run_at,
            created_at=s.created_at,
            updated_at=s.updated_at,
            is_scheduled=is_scheduled.get(s.id, False),
            schedule_enabled=schedule_enabled.get(s.id, False),
            last_scheduled_status=last_status.get(s.id),
        )
        for s in scripts
    ]


@router.post("", response_model=SqlScriptRead, status_code=status.HTTP_201_CREATED)
def create_script(payload: SqlScriptCreate, db: Session = Depends(get_db)) -> SqlScript:
    script = SqlScript(name=payload.name, content=payload.content, description=payload.description)
    db.add(script)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="A script with that name already exists") from e
    db.refresh(script)
    return script


@router.get("/{script_id}", response_model=SqlScriptRead)
def get_script(script_id: uuid.UUID, db: Session = Depends(get_db)) -> SqlScript:
    script = db.get(SqlScript, script_id)
    if script is None:
        raise HTTPException(404, "Script not found")
    return script


@router.put("/{script_id}", response_model=SqlScriptRead)
def update_script(
    script_id: uuid.UUID, payload: SqlScriptUpdate, db: Session = Depends(get_db)
) -> SqlScript:
    script = db.get(SqlScript, script_id)
    if script is None:
        raise HTTPException(404, "Script not found")
    if payload.name is not None:
        script.name = payload.name
    if payload.content is not None:
        script.content = payload.content
    if payload.description is not None:
        script.description = payload.description
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="A script with that name already exists") from e
    db.refresh(script)
    return script


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_script(script_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    script = db.get(SqlScript, script_id)
    if script is None:
        raise HTTPException(404, "Script not found")
    db.delete(script)
    db.commit()


@router.post("/{script_id}/run", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def run_script(
    script_id: uuid.UUID, payload: SqlScriptRunRequest, db: Session = Depends(get_db)
) -> JobEnqueued:
    script = db.get(SqlScript, script_id)
    if script is None:
        raise HTTPException(404, "Script not found")
    # Validate up front that every requested connection exists, so the user gets a clean 404
    # instead of a per-card "deleted connection" error for an obvious typo.
    existing = set(
        db.execute(select(Connection.id).where(Connection.id.in_(payload.connection_ids))).scalars()
    )
    missing = [str(cid) for cid in payload.connection_ids if cid not in existing]
    if missing:
        raise HTTPException(404, f"Unknown connection(s): {', '.join(missing)}")
    job_id = await enqueue(
        "execute_sql_script",
        str(script_id),
        [str(cid) for cid in payload.connection_ids],
        not payload.allow_writes,  # read_only
    )
    return JobEnqueued(job_id=job_id)
