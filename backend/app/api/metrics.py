"""Dashboard metrics: totals, a per-day activity time series, and a run-status breakdown.

All derived from the metadata DB (no user-DB access), so it's a plain synchronous endpoint.
The time series buckets timestamped events (introspections, comparisons, migration / verification
/ pipeline / scheduled runs) by UTC day over a trailing window.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas_io import MetricsResponse, MetricsSeriesPoint, MetricsTotals
from app.db import get_db
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.migration_run import MigrationRun
from app.models.pipeline import Pipeline, PipelineRun
from app.models.scheduled_script import ScheduledRun, ScheduledScript
from app.models.schema_snapshot import SchemaSnapshot
from app.models.sql_script import SqlScript
from app.models.verification_run import VerificationRun

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _count(db: Session, model: Any) -> int:
    return int(db.execute(select(func.count()).select_from(model)).scalar_one())


def _counts_by_day(
    db: Session, ts_col: Any, start: datetime, buckets: dict[Any, int]
) -> dict[Any, int]:
    """Tally rows by UTC date into a copy of `buckets` (date -> 0)."""
    counts = dict(buckets)
    for ts in db.execute(select(ts_col).where(ts_col >= start)).scalars():
        if ts is None:
            continue
        d = (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC).date()
        if d in counts:
            counts[d] += 1
    return counts


def _normalize_status(raw: str) -> str:
    s = raw.lower()
    if s in ("succeeded", "passed"):
        return "succeeded"
    if s == "failed":
        return "failed"
    if s in ("running", "pending"):
        return "running"
    if s == "partial":
        return "partial"
    if s == "cancelled":
        return "cancelled"
    return "other"


@router.get("", response_model=MetricsResponse)
def get_metrics(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db)) -> MetricsResponse:
    now = datetime.now(UTC)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_list = [(start + timedelta(days=i)).date() for i in range(days)]
    zero = {d: 0 for d in day_list}

    # Totals.
    env_rows = db.execute(
        select(Connection.environment, func.count()).group_by(Connection.environment)
    ).all()
    by_env: dict[str, int] = {"development": 0, "staging": 0, "production": 0, "none": 0}
    for env, n in env_rows:
        by_env[env or "none"] = int(n)

    totals = MetricsTotals(
        connections=sum(by_env.values()),
        connections_by_env=by_env,
        snapshots=_count(db, SchemaSnapshot),
        comparisons=_count(db, Comparison),
        scripts=_count(db, SqlScript),
        pipelines=_count(db, Pipeline),
        schedules=_count(db, ScheduledScript),
        migration_runs=_count(db, MigrationRun),
        verification_runs=_count(db, VerificationRun),
        pipeline_runs=_count(db, PipelineRun),
        scheduled_runs=_count(db, ScheduledRun),
    )

    # Per-day series by event type.
    intro = _counts_by_day(db, SchemaSnapshot.captured_at, start, zero)
    cmp_ = _counts_by_day(db, Comparison.created_at, start, zero)
    mig = _counts_by_day(db, MigrationRun.created_at, start, zero)
    ver = _counts_by_day(db, VerificationRun.created_at, start, zero)
    pipe = _counts_by_day(db, PipelineRun.created_at, start, zero)
    sched = _counts_by_day(db, ScheduledRun.started_at, start, zero)

    series = [
        MetricsSeriesPoint(
            date=d.isoformat(),
            introspection=intro[d],
            comparison=cmp_[d],
            migration=mig[d],
            verification=ver[d],
            pipeline=pipe[d],
            scheduled=sched[d],
        )
        for d in day_list
    ]

    # Status breakdown across all run types within the window.
    breakdown: dict[str, int] = {}
    status_sources: list[tuple[Any, Any]] = [
        (MigrationRun.status, MigrationRun.created_at),
        (VerificationRun.status, VerificationRun.created_at),
        (PipelineRun.status, PipelineRun.created_at),
        (ScheduledRun.status, ScheduledRun.started_at),
    ]
    for status_col, ts_col in status_sources:
        for raw in db.execute(select(status_col).where(ts_col >= start)).scalars():
            key = _normalize_status(raw.value if hasattr(raw, "value") else str(raw))
            breakdown[key] = breakdown.get(key, 0) + 1

    return MetricsResponse(days=days, totals=totals, series=series, status_breakdown=breakdown)
