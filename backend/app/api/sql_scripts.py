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
from app.models.sql_script import SqlScript

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.get("", response_model=list[SqlScriptRead])
def list_scripts(db: Session = Depends(get_db)) -> list[SqlScript]:
    return list(db.execute(select(SqlScript).order_by(SqlScript.updated_at.desc())).scalars())


@router.post("", response_model=SqlScriptRead, status_code=status.HTTP_201_CREATED)
def create_script(payload: SqlScriptCreate, db: Session = Depends(get_db)) -> SqlScript:
    script = SqlScript(name=payload.name, content=payload.content)
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
        "execute_sql_script", str(script_id), [str(cid) for cid in payload.connection_ids]
    )
    return JobEnqueued(job_id=job_id)
