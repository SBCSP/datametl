from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    ComparisonCreate,
    ComparisonEnqueued,
    ComparisonRead,
    ComparisonReport,
    ConnectionSummary,
    SnapshotInReport,
)
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.schema_snapshot import SchemaSnapshot

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


@router.get("", response_model=list[ComparisonRead])
def list_comparisons(db: Session = Depends(get_db)) -> list[Comparison]:
    return list(db.execute(select(Comparison).order_by(Comparison.created_at.desc())).scalars())


@router.post("", response_model=ComparisonEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def create_comparison(payload: ComparisonCreate, db: Session = Depends(get_db)) -> ComparisonEnqueued:
    if db.get(SchemaSnapshot, payload.source_snapshot_id) is None:
        raise HTTPException(404, "source snapshot not found")
    if db.get(SchemaSnapshot, payload.dest_snapshot_id) is None:
        raise HTTPException(404, "dest snapshot not found")

    # Schema scope is opt-in; both must be set to take effect. Empty strings get normalized to None.
    src_sch = (payload.source_schema or None) or None
    dst_sch = (payload.dest_schema or None) or None
    if (src_sch is None) != (dst_sch is None):
        raise HTTPException(400, "Provide both source_schema and dest_schema, or neither")

    cmp = Comparison(
        source_snapshot_id=payload.source_snapshot_id,
        dest_snapshot_id=payload.dest_snapshot_id,
        source_schema=src_sch,
        dest_schema=dst_sch,
        diff={},
    )
    db.add(cmp)
    db.commit()

    job_id = await enqueue("run_comparison", str(cmp.id))
    return ComparisonEnqueued(comparison_id=cmp.id, job_id=job_id)


@router.get("/{comparison_id}", response_model=ComparisonRead)
def get_comparison(comparison_id: uuid.UUID, db: Session = Depends(get_db)) -> Comparison:
    cmp = db.get(Comparison, comparison_id)
    if cmp is None:
        raise HTTPException(404, "Comparison not found")
    return cmp


@router.get("/{comparison_id}/report", response_model=ComparisonReport)
def get_comparison_report(comparison_id: uuid.UUID, db: Session = Depends(get_db)) -> ComparisonReport:
    """One-shot endpoint that returns everything the report / shareable view needs:
    diff + both snapshots' summary stats and warnings + both connections' display names."""
    cmp = db.get(Comparison, comparison_id)
    if cmp is None:
        raise HTTPException(404, "Comparison not found")

    src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
    dst_snap = db.get(SchemaSnapshot, cmp.dest_snapshot_id)
    if src_snap is None or dst_snap is None:
        raise HTTPException(500, "Comparison references a missing snapshot")

    src_conn = db.get(Connection, src_snap.connection_id)
    dst_conn = db.get(Connection, dst_snap.connection_id)
    if src_conn is None or dst_conn is None:
        raise HTTPException(500, "Snapshot references a missing connection")

    return ComparisonReport(
        id=cmp.id,
        created_at=cmp.created_at,
        diff=cmp.diff,
        source_schema=cmp.source_schema,
        dest_schema=cmp.dest_schema,
        source_connection=ConnectionSummary(id=src_conn.id, name=src_conn.name, engine=src_conn.engine),
        dest_connection=ConnectionSummary(id=dst_conn.id, name=dst_conn.name, engine=dst_conn.engine),
        source_snapshot=_summarize(src_snap),
        dest_snapshot=_summarize(dst_snap),
    )


def _summarize(snap: SchemaSnapshot) -> SnapshotInReport:
    s = snap.normalized_schema or {}
    return SnapshotInReport(
        id=snap.id,
        captured_at=snap.captured_at,
        server_version=s.get("server_version"),
        table_count=len(s.get("tables", [])),
        view_count=len(s.get("views", [])),
        extension_count=len(s.get("extensions", [])),
        rls_policy_count=len(s.get("rls_policies", [])),
        warnings=snap.warnings or [],
    )
