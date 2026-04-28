"""Unified activity log — every long-running operation in one timeline.

Pulls recent rows from `schema_snapshots` (introspections), `comparisons`, `migration_runs`,
and `verification_runs`, normalizes them into a single ActivityEntry shape, sorts by time.

This is a debugging / observability surface — answers "what's the system doing right now"
and "what failed in the last few hours" without having to hunt through five different pages.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import ActivityEntry
from app.db import get_db
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.migration_run import MigrationRun
from app.models.schema_snapshot import SchemaSnapshot
from app.models.verification_run import VerificationRun

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityEntry])
def list_activity(
    db: Session = Depends(get_db),
    limit_per_type: int = Query(50, ge=1, le=500),
) -> list[ActivityEntry]:
    """Return recent activity across all run types, sorted newest first.

    `limit_per_type` caps how many we pull from each source before sorting/merging — the
    final list size is at most 4 × limit_per_type.
    """
    out: list[ActivityEntry] = []

    # Introspections — each successful snapshot was an introspect job.
    snap_rows = list(
        db.execute(
            select(SchemaSnapshot)
            .order_by(SchemaSnapshot.captured_at.desc())
            .limit(limit_per_type)
        ).scalars()
    )
    conn_ids = {s.connection_id for s in snap_rows}
    conns: dict[Any, Connection] = {
        c.id: c
        for c in db.execute(select(Connection).where(Connection.id.in_(conn_ids))).scalars()
    }
    for s in snap_rows:
        c = conns.get(s.connection_id)
        sch = s.normalized_schema or {}
        table_count = len(sch.get("tables", []))
        warn_count = len(s.warnings or [])
        out.append(
            ActivityEntry(
                type="introspection",
                id=str(s.id),
                label=f"Introspect: {c.name if c else s.connection_id}",
                status="succeeded",
                started_at=s.captured_at,
                finished_at=s.captured_at,
                detail=f"{table_count} tables, {warn_count} warnings",
                href=f"/schemas/{s.connection_id}",
            )
        )

    # Comparisons.
    cmp_rows = list(
        db.execute(select(Comparison).order_by(Comparison.created_at.desc()).limit(limit_per_type)).scalars()
    )
    for c in cmp_rows:
        d = c.diff or {}
        common = len(d.get("common_tables") or [])
        only_src = len(d.get("tables_only_in_source") or [])
        only_dst = len(d.get("tables_only_in_dest") or [])
        ready = bool(d) and (common or only_src or only_dst)
        scope = (
            f"schema {c.source_schema} → {c.dest_schema}"
            if c.source_schema and c.dest_schema
            else "all schemas"
        )
        out.append(
            ActivityEntry(
                type="comparison",
                id=str(c.id),
                label=f"Comparison ({scope})",
                status="succeeded" if ready else "running",
                started_at=c.created_at,
                finished_at=c.created_at if ready else None,
                detail=f"{common} common, {only_src} only-in-source, {only_dst} only-in-dest"
                if ready
                else "computing…",
                href=f"/comparisons/{c.id}",
            )
        )

    # Migration runs.
    mig_rows = list(
        db.execute(select(MigrationRun).order_by(MigrationRun.created_at.desc()).limit(limit_per_type)).scalars()
    )
    for m in mig_rows:
        plan = m.plan or {}
        n = len(plan.get("included") or [])
        out.append(
            ActivityEntry(
                type="migration",
                id=str(m.id),
                label=f"Migration ({n} table{'s' if n != 1 else ''})",
                status=m.status.value,
                # Surface created_at when the run hasn't started yet so pending runs sort
                # to where the user expects (near the top) instead of the bottom.
                started_at=m.started_at or m.created_at,
                finished_at=m.finished_at,
                detail=m.error or None,
                href=f"/migrations/{m.id}",
            )
        )

    # Verification runs.
    ver_rows = list(
        db.execute(select(VerificationRun).order_by(VerificationRun.created_at.desc()).limit(limit_per_type)).scalars()
    )
    for v in ver_rows:
        plan = v.plan or {}
        n = len([t for t in (plan.get("tables") or []) if t.get("include", True)])
        out.append(
            ActivityEntry(
                type="verification",
                id=str(v.id),
                label=f"Verification ({n} table{'s' if n != 1 else ''})",
                status=v.status.value,
                started_at=v.started_at or v.created_at,
                finished_at=v.finished_at,
                detail=v.error or None,
                href=f"/verification/{v.id}",
            )
        )

    # Sort newest first. Every entry has at least one timestamp; use a UTC-anchored
    # min as a safety net so the comparator never sees a None.
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def _sort_key(e: ActivityEntry) -> datetime:
        return e.finished_at or e.started_at or epoch

    out.sort(key=_sort_key, reverse=True)
    return out
