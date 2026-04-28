from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import MappingRead, MappingUpdate
from app.db import get_db
from app.introspection.normalized import Schema
from app.mapping.registry import is_lossy
from app.models.comparison import Comparison
from app.models.mapping import Mapping
from app.models.schema_snapshot import SchemaSnapshot

router = APIRouter(prefix="/api/comparisons", tags=["mappings"])


@router.get("/{comparison_id}/mappings", response_model=list[MappingRead])
def list_mappings(comparison_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Mapping]:
    if db.get(Comparison, comparison_id) is None:
        raise HTTPException(404, "Comparison not found")
    return list(
        db.execute(
            select(Mapping)
            .where(Mapping.comparison_id == comparison_id)
            .order_by(Mapping.source_table, Mapping.source_column)
        ).scalars()
    )


@router.put("/{comparison_id}/mappings/{mapping_id}", response_model=MappingRead)
def update_mapping(
    comparison_id: uuid.UUID,
    mapping_id: uuid.UUID,
    payload: MappingUpdate,
    db: Session = Depends(get_db),
) -> Mapping:
    m = db.get(Mapping, mapping_id)
    if m is None or m.comparison_id != comparison_id:
        raise HTTPException(404, "Mapping not found")

    if payload.dest_table is not None:
        m.dest_table = payload.dest_table
    if payload.dest_column is not None:
        m.dest_column = payload.dest_column
    if payload.notes is not None:
        m.notes = payload.notes

    if payload.override_dest_type is not None:
        m.override_dest_type = payload.override_dest_type or None
        # Recompute is_lossy based on the override's normalized type. Cheap since we already
        # have the source snapshot loaded.
        m.is_lossy = _recompute_lossy(db, m)

    db.commit()
    db.refresh(m)
    return m


def _recompute_lossy(db: Session, m: Mapping) -> bool:
    """Look up source + dest normalized types from the comparison's snapshots and compare."""
    cmp = db.get(Comparison, m.comparison_id)
    if cmp is None:
        return False
    src_snap = db.get(SchemaSnapshot, cmp.source_snapshot_id)
    dst_snap = db.get(SchemaSnapshot, cmp.dest_snapshot_id)
    if src_snap is None or dst_snap is None:
        return False

    src_schema = Schema.model_validate(src_snap.normalized_schema)
    dst_schema = Schema.model_validate(dst_snap.normalized_schema)
    src_norm = _find_normalized(src_schema, m.source_table, m.source_column)
    dst_norm = _find_normalized(dst_schema, m.dest_table, m.dest_column)
    if src_norm and dst_norm:
        return is_lossy(src_norm, dst_norm)
    return False


def _find_normalized(schema: Schema, qualified_table: str, column: str) -> str | None:
    for t in schema.tables:
        if t.qualified_name == qualified_table:
            for c in t.columns:
                if c.name == column:
                    return c.normalized_type
    return None
