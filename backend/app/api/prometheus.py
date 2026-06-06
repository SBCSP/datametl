"""Prometheus scrape endpoint at /metrics (text exposition format 0.0.4).

Distinct from /api/metrics (the dashboard's JSON). Lives outside /api so it isn't gated by the
in-app AUTH_ENABLED middleware; set METRICS_TOKEN to require a bearer token from the scraper.
Dependency-free — gauges are sampled straight from the metadata DB at scrape time, so values are
always current and survive restarts (no in-process counters to reset).
"""
from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as cfg
from app.db import get_db
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.introspection_run import IntrospectionRun
from app.models.migration_run import MigrationRun
from app.models.pipeline import Pipeline, PipelineRun
from app.models.scheduled_script import ScheduledRun, ScheduledScript
from app.models.schema_snapshot import SchemaSnapshot
from app.models.sql_script import SqlScript
from app.models.tap import Tap, TapRun
from app.models.verification_run import VerificationRun

router = APIRouter(tags=["meta"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_VERSION = "0.2.6"

# type, model — run tables exposed as datametl_runs_total{type,status}
_RUN_MODELS: list[tuple[str, Any]] = [
    ("migration", MigrationRun),
    ("verification", VerificationRun),
    ("pipeline", PipelineRun),
    ("scheduled", ScheduledRun),
    ("tap", TapRun),
    ("introspection", IntrospectionRun),
]

# A metric family: (name, help, [(labels, value)])
Family = tuple[str, str, list[tuple[dict[str, str], float]]]


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(d: dict[str, str]) -> str:
    if not d:
        return ""
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in d.items()) + "}"


def _status(s: Any) -> str:
    return (s.value if hasattr(s, "value") else str(s)).lower()


def _count(db: Session, model: Any) -> int:
    return int(db.execute(select(func.count()).select_from(model)).scalar_one())


def _collect(db: Session) -> list[Family]:
    conn_rows = db.execute(
        select(Connection.environment, func.count()).group_by(Connection.environment)
    ).all()
    sched_rows = db.execute(
        select(ScheduledScript.target_kind, ScheduledScript.enabled, func.count()).group_by(
            ScheduledScript.target_kind, ScheduledScript.enabled
        )
    ).all()

    run_samples: list[tuple[dict[str, str], float]] = []
    for typ, model in _RUN_MODELS:
        for st, n in db.execute(select(model.status, func.count()).group_by(model.status)).all():
            run_samples.append(({"type": typ, "status": _status(st)}, float(n)))

    return [
        ("datametl_build_info", "Build info (value always 1).", [({"version": _VERSION}, 1.0)]),
        (
            "datametl_connections",
            "Configured connections by environment.",
            [({"environment": env or "none"}, float(n)) for env, n in conn_rows],
        ),
        ("datametl_snapshots_total", "Schema snapshots captured.", [({}, float(_count(db, SchemaSnapshot)))]),
        ("datametl_comparisons_total", "Schema comparisons.", [({}, float(_count(db, Comparison)))]),
        ("datametl_scripts_total", "Saved SQL scripts.", [({}, float(_count(db, SqlScript)))]),
        ("datametl_pipelines_total", "ETL pipelines.", [({}, float(_count(db, Pipeline)))]),
        ("datametl_taps_total", "API taps (data sources).", [({}, float(_count(db, Tap)))]),
        (
            "datametl_schedules",
            "Schedules by target kind and enabled state.",
            [
                ({"kind": k or "script", "enabled": str(bool(en)).lower()}, float(n))
                for k, en, n in sched_rows
            ],
        ),
        ("datametl_runs_total", "Run records by type and status.", run_samples),
    ]


def _render(families: list[Family], queue_depth: int) -> str:
    out: list[str] = []
    for name, help_, samples in families:
        out.append(f"# HELP {name} {_esc(help_)}")
        out.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            v = int(value) if float(value).is_integer() else value
            out.append(f"{name}{_labels(labels)} {v}")
    if queue_depth >= 0:
        out.append("# HELP datametl_queue_depth Pending jobs in the arq queue.")
        out.append("# TYPE datametl_queue_depth gauge")
        out.append(f"datametl_queue_depth {queue_depth}")
    return "\n".join(out) + "\n"


async def _queue_depth() -> int:
    """ZCARD of the arq queue; -1 (omitted) if Redis is unreachable."""
    try:
        pool = await create_pool(RedisSettings.from_dsn(cfg.redis_url))
        try:
            return int(await pool.zcard("arq:queue"))
        finally:
            await pool.close()
    except Exception:
        return -1


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request, db: Session = Depends(get_db)) -> Response:
    if not cfg.metrics_enabled:
        raise HTTPException(404, "Metrics endpoint disabled")
    if cfg.metrics_token:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if token != cfg.metrics_token:
            raise HTTPException(401, "Invalid metrics token")
    body = _render(_collect(db), await _queue_depth())
    return Response(content=body, media_type=CONTENT_TYPE)
