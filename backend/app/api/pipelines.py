from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    PipelineCreate,
    PipelineRead,
    PipelineRunEnqueued,
    PipelineRunRead,
    PipelineRunStepRead,
    PipelineRunSummary,
    PipelineStepIO,
    PipelineStepRead,
    PipelineSummary,
    PipelineUpdate,
)
from app.db import get_db
from app.etl.runner import create_pipeline_run
from app.jobs.queue import enqueue
from app.models.connection import Connection
from app.models.pipeline import Pipeline, PipelineRun, PipelineRunStep, PipelineStep
from app.models.sql_script import SqlScript

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


# --- validation helpers ---

def _validate_step(idx: int, step: PipelineStepIO) -> None:
    cfg = step.config or {}
    where = f"step {idx + 1}"
    if step.step_type == "sql":
        if not cfg.get("connection_id"):
            raise HTTPException(422, f"{where}: SQL step needs a connection")
        if not cfg.get("script_id") and not (cfg.get("inline_sql") or "").strip():
            raise HTTPException(422, f"{where}: SQL step needs a saved script or inline SQL")
    elif step.step_type == "transfer":
        if not cfg.get("source_connection_id"):
            raise HTTPException(422, f"{where}: transfer needs a source connection")
        if not cfg.get("dest_connection_id"):
            raise HTTPException(422, f"{where}: transfer needs a destination connection")
        if not cfg.get("source_script_id") and not (cfg.get("source_sql") or "").strip():
            raise HTTPException(422, f"{where}: transfer needs a source script or SELECT")
        if not (cfg.get("dest_table") or "").strip():
            raise HTTPException(422, f"{where}: transfer needs a destination table")
        if cfg.get("mode") not in (None, "truncate", "append"):
            raise HTTPException(422, f"{where}: transfer mode must be 'truncate' or 'append'")


def _validate_references(db: Session, steps: list[PipelineStepIO]) -> None:
    """Fail fast if any referenced connection or script doesn't exist."""
    conn_ids: set[uuid.UUID] = set()
    script_ids: set[uuid.UUID] = set()
    for s in steps:
        cfg = s.config or {}
        for key in ("connection_id", "source_connection_id", "dest_connection_id"):
            if cfg.get(key):
                conn_ids.add(uuid.UUID(str(cfg[key])))
        for key in ("script_id", "source_script_id"):
            if cfg.get(key):
                script_ids.add(uuid.UUID(str(cfg[key])))
    if conn_ids:
        found = set(db.execute(select(Connection.id).where(Connection.id.in_(conn_ids))).scalars())
        missing = [str(c) for c in conn_ids if c not in found]
        if missing:
            raise HTTPException(404, f"Unknown connection(s): {', '.join(missing)}")
    if script_ids:
        found = set(db.execute(select(SqlScript.id).where(SqlScript.id.in_(script_ids))).scalars())
        missing = [str(c) for c in script_ids if c not in found]
        if missing:
            raise HTTPException(404, f"Unknown script(s): {', '.join(missing)}")


def _replace_steps(db: Session, pipeline_id: uuid.UUID, steps: list[PipelineStepIO]) -> None:
    db.execute(delete(PipelineStep).where(PipelineStep.pipeline_id == pipeline_id))
    for i, s in enumerate(steps):
        db.add(
            PipelineStep(
                pipeline_id=pipeline_id,
                step_order=i,
                name=s.name,
                step_type=s.step_type,
                config=s.config or {},
            )
        )


def _to_read(db: Session, pipeline: Pipeline) -> PipelineRead:
    steps = list(
        db.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_id == pipeline.id)
            .order_by(PipelineStep.step_order)
        ).scalars()
    )
    return PipelineRead(
        id=pipeline.id,
        name=pipeline.name,
        description=pipeline.description,
        steps=[
            PipelineStepRead(
                id=s.id, step_order=s.step_order, name=s.name, step_type=s.step_type, config=s.config or {}
            )
            for s in steps
        ],
        created_at=pipeline.created_at,
        updated_at=pipeline.updated_at,
    )


# --- pipeline CRUD ---

@router.get("", response_model=list[PipelineSummary])
def list_pipelines(db: Session = Depends(get_db)) -> list[PipelineSummary]:
    pipelines = list(db.execute(select(Pipeline).order_by(Pipeline.updated_at.desc())).scalars())

    counts: dict[uuid.UUID, int] = {}
    for pid, n in db.execute(
        select(PipelineStep.pipeline_id, func.count()).group_by(PipelineStep.pipeline_id)
    ).all():
        counts[pid] = n

    last_status: dict[uuid.UUID, str] = {}
    last_at: dict[uuid.UUID, datetime] = {}
    for pid, st, at in db.execute(
        select(PipelineRun.pipeline_id, PipelineRun.status, PipelineRun.created_at)
        .order_by(PipelineRun.pipeline_id, PipelineRun.created_at.desc())
        .distinct(PipelineRun.pipeline_id)
    ).all():
        last_status[pid] = st
        last_at[pid] = at

    return [
        PipelineSummary(
            id=p.id,
            name=p.name,
            description=p.description,
            step_count=counts.get(p.id, 0),
            last_run_status=last_status.get(p.id),
            last_run_at=last_at.get(p.id),
            updated_at=p.updated_at,
        )
        for p in pipelines
    ]


@router.post("", response_model=PipelineRead, status_code=status.HTTP_201_CREATED)
def create_pipeline(payload: PipelineCreate, db: Session = Depends(get_db)) -> PipelineRead:
    for i, s in enumerate(payload.steps):
        _validate_step(i, s)
    _validate_references(db, payload.steps)

    pipeline = Pipeline(name=payload.name, description=payload.description)
    db.add(pipeline)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A pipeline with that name already exists") from e
    _replace_steps(db, pipeline.id, payload.steps)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A pipeline with that name already exists") from e
    db.refresh(pipeline)
    return _to_read(db, pipeline)


# Declared before "/{pipeline_id}" so "runs" is never captured as a pipeline id.
@router.get("/runs/{run_id}", response_model=PipelineRunRead)
def get_pipeline_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> PipelineRunRead:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(404, "Pipeline run not found")
    steps = list(
        db.execute(
            select(PipelineRunStep)
            .where(PipelineRunStep.run_id == run.id)
            .order_by(PipelineRunStep.step_order)
        ).scalars()
    )
    return PipelineRunRead(
        id=run.id,
        pipeline_id=run.pipeline_id,
        status=run.status,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        steps=[
            PipelineRunStepRead(
                id=s.id, step_order=s.step_order, name=s.name, step_type=s.step_type,
                status=s.status, summary=s.summary or {}, error=s.error,
                started_at=s.started_at, finished_at=s.finished_at,
            )
            for s in steps
        ],
    )


@router.get("/{pipeline_id}", response_model=PipelineRead)
def get_pipeline(pipeline_id: uuid.UUID, db: Session = Depends(get_db)) -> PipelineRead:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    return _to_read(db, pipeline)


@router.put("/{pipeline_id}", response_model=PipelineRead)
def update_pipeline(
    pipeline_id: uuid.UUID, payload: PipelineUpdate, db: Session = Depends(get_db)
) -> PipelineRead:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    if payload.name is not None:
        pipeline.name = payload.name
    if payload.description is not None:
        pipeline.description = payload.description
    if payload.steps is not None:
        for i, s in enumerate(payload.steps):
            _validate_step(i, s)
        _validate_references(db, payload.steps)
        _replace_steps(db, pipeline.id, payload.steps)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A pipeline with that name already exists") from e
    db.refresh(pipeline)
    return _to_read(db, pipeline)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipeline(pipeline_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    db.delete(pipeline)
    db.commit()


# --- runs ---

@router.post("/{pipeline_id}/runs", response_model=PipelineRunEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def create_run(pipeline_id: uuid.UUID, db: Session = Depends(get_db)) -> PipelineRunEnqueued:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    try:
        run = create_pipeline_run(db, pipeline_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job_id = await enqueue("run_pipeline", str(run.id))
    return PipelineRunEnqueued(run_id=run.id, job_id=job_id)


@router.get("/{pipeline_id}/runs", response_model=list[PipelineRunSummary])
def list_runs(pipeline_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PipelineRunSummary]:
    runs = list(
        db.execute(
            select(PipelineRun)
            .where(PipelineRun.pipeline_id == pipeline_id)
            .order_by(PipelineRun.created_at.desc())
            .limit(50)
        ).scalars()
    )
    step_counts: dict[uuid.UUID, int] = {}
    if runs:
        for rid, n in db.execute(
            select(PipelineRunStep.run_id, func.count())
            .where(PipelineRunStep.run_id.in_([r.id for r in runs]))
            .group_by(PipelineRunStep.run_id)
        ).all():
            step_counts[rid] = n
    return [
        PipelineRunSummary(
            id=r.id,
            pipeline_id=r.pipeline_id,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            step_count=step_counts.get(r.id, 0),
            created_at=r.created_at,
        )
        for r in runs
    ]
