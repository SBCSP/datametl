"""Execute an ETL pipeline run, step by step, recording live per-step progress.

Sequential, stop-on-error: if a step fails, the remaining steps are marked ``skipped`` and the
run is ``failed``. Each step commits its status before/after executing so the UI can poll
progress. Mirrors the migration runner's shape, but steps are heterogeneous (sql | transfer).

Safety: ``sql`` steps run read-only unless the step opted into writes; ``transfer`` always reads
the source read-only (see app/etl/transfer.py). Writes only hit destinations the operator chose.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.connectors import for_engine
from app.connectors.postgres import PostgresConnector
from app.crypto import vault
from app.models.connection import Connection
from app.models.pipeline import Pipeline, PipelineRun, PipelineRunStep, PipelineStep
from app.models.sql_script import SqlScript
from app.scripts.runner import ROW_CAP, split_statements

log = logging.getLogger("datametl.etl.runner")

# ETL steps are intentional batch operations (large upserts, full transforms), so we don't
# impose a per-statement timeout — the arq job_timeout (30 min) is the backstop.
STEP_TIMEOUT_S = 0


def create_pipeline_run(db: Session, pipeline_id: uuid.UUID) -> PipelineRun:
    """Persist a PipelineRun + a snapshot of the pipeline's current steps (status=pending)."""
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise ValueError(f"Unknown pipeline: {pipeline_id}")
    steps = list(
        db.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_id == pipeline_id)
            .order_by(PipelineStep.step_order)
        ).scalars()
    )
    if not steps:
        raise ValueError("Pipeline has no steps")

    run = PipelineRun(pipeline_id=pipeline_id, status="pending")
    db.add(run)
    db.flush()
    for s in steps:
        db.add(
            PipelineRunStep(
                run_id=run.id,
                step_order=s.step_order,
                name=s.name,
                step_type=s.step_type,
                config=s.config,
                status="pending",
            )
        )
    db.commit()
    db.refresh(run)
    return run


def _connection(db: Session, cid: str | None) -> tuple[str, str, dict[str, Any]]:
    if not cid:
        raise ValueError("step is missing a connection")
    conn = db.get(Connection, uuid.UUID(str(cid)))
    if conn is None:
        raise ValueError(f"connection not found: {cid}")
    return conn.name, conn.engine, vault.decrypt(conn.encrypted_credentials)


def _resolve_sql(db: Session, *, script_id: str | None, inline_sql: str | None) -> str:
    if script_id:
        script = db.get(SqlScript, uuid.UUID(str(script_id)))
        if script is None:
            raise ValueError(f"script not found: {script_id}")
        return script.content
    return inline_sql or ""


def _run_sql_step(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    name, engine, creds = _connection(db, config.get("connection_id"))
    content = _resolve_sql(db, script_id=config.get("script_id"), inline_sql=config.get("inline_sql"))
    statements = split_statements(content)
    if not statements:
        raise ValueError("sql step has no statements")
    read_only = not bool(config.get("allow_writes"))
    stmts = for_engine(engine, creds).run_statements(statements, ROW_CAP, STEP_TIMEOUT_S, read_only)
    first_err = next((s["error"] for s in stmts if s["error"]), None)
    summary = {
        "connection": name,
        "read_only": read_only,
        "statement_count": len(stmts),
        "rows": sum(int(s["row_count"] or 0) for s in stmts),
        "statements": [
            {"index": s["index"], "kind": s["kind"], "row_count": s["row_count"],
             "duration_ms": s["duration_ms"], "error": s["error"]}
            for s in stmts
        ],
    }
    if first_err is not None:
        raise StepError(first_err, summary)
    return summary


def _run_transfer_step(db: Session, config: dict[str, Any], engines: dict[str, Engine]) -> dict[str, Any]:
    # Imported here so the migration path never imports the ETL transfer module transitively.
    from app.etl.transfer import stream_query_to_table

    src_name, src_engine_name, src_creds = _connection(db, config.get("source_connection_id"))
    dst_name, dst_engine_name, dst_creds = _connection(db, config.get("dest_connection_id"))
    if src_engine_name != "postgres" or dst_engine_name != "postgres":
        raise ValueError("transfer steps support Postgres connections only (for now)")
    source_sql = _resolve_sql(
        db, script_id=config.get("source_script_id"), inline_sql=config.get("source_sql")
    )
    if not source_sql.strip():
        raise ValueError("transfer step has no source SQL")
    dest_table = str(config.get("dest_table") or "").strip()
    if not dest_table:
        raise ValueError("transfer step has no destination table")
    dest_columns = config.get("dest_columns") or None
    mode = str(config.get("mode") or "truncate")

    src_engine = _engine_for(engines, f"src:{config.get('source_connection_id')}", src_creds)
    dst_engine = _engine_for(engines, f"dst:{config.get('dest_connection_id')}", dst_creds)
    result = stream_query_to_table(
        src_engine, dst_engine,
        source_sql=source_sql, dest_table=dest_table, dest_columns=dest_columns, mode=mode,
    )
    return {
        "source_connection": src_name,
        "dest_connection": dst_name,
        "dest_table": dest_table,
        "mode": mode,
        "rows_written": result["rows_written"],
        "detail": result["detail"],
    }


def _engine_for(cache: dict[str, Engine], key: str, creds: dict[str, Any]) -> Engine:
    if key not in cache:
        cache[key] = PostgresConnector(creds)._engine()
    return cache[key]


class StepError(Exception):
    """A step failed but produced a partial summary worth recording."""

    def __init__(self, message: str, summary: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.summary = summary or {}


def execute_pipeline_run(db: Session, run_id: uuid.UUID) -> dict[str, Any]:
    run = db.get(PipelineRun, run_id)
    if run is None:
        raise ValueError(f"Unknown pipeline run: {run_id}")

    run.status = "running"
    run.started_at = datetime.now(tz=timezone.utc)
    db.commit()

    steps = list(
        db.execute(
            select(PipelineRunStep)
            .where(PipelineRunStep.run_id == run_id)
            .order_by(PipelineRunStep.step_order)
        ).scalars()
    )

    engines: dict[str, Engine] = {}
    failed = False
    failure_msg: str | None = None
    try:
        for step in steps:
            if failed:
                step.status = "skipped"
                db.commit()
                continue

            step.status = "running"
            step.started_at = datetime.now(tz=timezone.utc)
            db.commit()

            try:
                if step.step_type == "sql":
                    summary = _run_sql_step(db, step.config or {})
                elif step.step_type == "transfer":
                    summary = _run_transfer_step(db, step.config or {}, engines)
                else:
                    raise ValueError(f"unknown step type: {step.step_type}")
                step.summary = summary
                step.status = "succeeded"
                step.finished_at = datetime.now(tz=timezone.utc)
                db.commit()
            except StepError as e:
                step.summary = e.summary
                step.status = "failed"
                step.error = str(e)
                step.finished_at = datetime.now(tz=timezone.utc)
                db.commit()
                failed = True
                failure_msg = str(e)
            except Exception as e:  # connection-level / transfer failure
                step.status = "failed"
                step.error = str(getattr(e, "__cause__", None) or e)
                step.finished_at = datetime.now(tz=timezone.utc)
                db.commit()
                failed = True
                failure_msg = step.error
    finally:
        for eng in engines.values():
            try:
                eng.dispose()
            except Exception:  # noqa: BLE001
                pass

    run.status = "failed" if failed else "succeeded"
    run.error = failure_msg
    run.finished_at = datetime.now(tz=timezone.utc)
    db.commit()
    return {"run_id": str(run_id), "status": run.status}
