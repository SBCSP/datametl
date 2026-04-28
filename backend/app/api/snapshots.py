from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import SchemaSummary, SnapshotRead, SnapshotSummary
from app.db import get_db
from app.models.connection import Connection
from app.models.schema_snapshot import SchemaSnapshot

router = APIRouter(prefix="/api", tags=["snapshots"])


@router.get("/connections/{connection_id}/snapshots", response_model=list[SnapshotSummary])
def list_snapshots(connection_id: uuid.UUID, db: Session = Depends(get_db)) -> list[SnapshotSummary]:
    if db.get(Connection, connection_id) is None:
        raise HTTPException(404, "Connection not found")
    rows = db.execute(
        select(SchemaSnapshot)
        .where(SchemaSnapshot.connection_id == connection_id)
        .order_by(SchemaSnapshot.captured_at.desc())
    ).scalars()
    return [
        SnapshotSummary(
            id=s.id,
            connection_id=s.connection_id,
            captured_at=s.captured_at,
            table_count=len(s.normalized_schema.get("tables", [])),
            warning_count=len(s.warnings or []),
        )
        for s in rows
    ]


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(snapshot_id: uuid.UUID, db: Session = Depends(get_db)) -> SnapshotRead:
    s = db.get(SchemaSnapshot, snapshot_id)
    if s is None:
        raise HTTPException(404, "Snapshot not found")
    return SnapshotRead(
        id=s.id,
        connection_id=s.connection_id,
        captured_at=s.captured_at,
        normalized_schema=s.normalized_schema,
        warnings=s.warnings or [],
    )


@router.get("/snapshots/{snapshot_id}/schemas", response_model=list[SchemaSummary])
def list_snapshot_schemas(snapshot_id: uuid.UUID, db: Session = Depends(get_db)) -> list[SchemaSummary]:
    """Per-schema counts inside a snapshot — fuels the schema picker on New comparison."""
    s = db.get(SchemaSnapshot, snapshot_id)
    if s is None:
        raise HTTPException(404, "Snapshot not found")
    schema_dict = s.normalized_schema or {}
    counts: dict[str, dict[str, int]] = {}
    for t in schema_dict.get("tables", []):
        bucket = counts.setdefault(t["schema"], {"tables": 0, "views": 0})
        bucket["tables"] += 1
    for v in schema_dict.get("views", []):
        bucket = counts.setdefault(v["schema"], {"tables": 0, "views": 0})
        bucket["views"] += 1
    return [
        SchemaSummary(name=name, table_count=c["tables"], view_count=c["views"])
        for name, c in sorted(counts.items())
    ]
