"""When a comparison is created we auto-seed mapping rows for every (source table, source column)
that has a matching destination table. The user can later override per-column type or rewire to
a different destination column.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.introspection.normalized import Schema, Table
from app.mapping.registry import default_dest_type, is_lossy
from app.models.mapping import Mapping


def seed_mappings_for_comparison(
    db: Session,
    *,
    comparison_id: uuid.UUID,
    source: Schema,
    dest: Schema,
    source_schema: str | None = None,
    dest_schema: str | None = None,
) -> int:
    """Create one Mapping row per source column that has a same-named destination table.

    Default: match tables across the whole snapshot by qualified name (`schema.table`).

    Schema-scoped: when both `source_schema` and `dest_schema` are provided, only the
    chosen schemas are considered, and tables are matched on bare name. This supports
    cross-schema migration (`prod.public.users` → `staging.legacy.users`).

    Returns the count inserted.
    """
    if source_schema is not None and dest_schema is not None:
        src_tables = [t for t in source.tables if t.schema_ == source_schema]
        dst_tables_by_name = {t.name: t for t in dest.tables if t.schema_ == dest_schema}
        match_key = lambda t: dst_tables_by_name.get(t.name)  # noqa: E731
    else:
        src_tables = list(source.tables)
        dst_tables_by_qn = {t.qualified_name: t for t in dest.tables}
        match_key = lambda t: dst_tables_by_qn.get(t.qualified_name)  # noqa: E731

    inserted = 0
    for src_table in src_tables:
        dest_table = match_key(src_table)
        if dest_table is None:
            # Tables only in source get no auto-mapping; the user can manually wire them later.
            continue
        inserted += _seed_for_table(db, comparison_id, source.engine, dest.engine, src_table, dest_table)

    db.flush()
    return inserted


def _seed_for_table(
    db: Session,
    comparison_id: uuid.UUID,
    source_engine: str,
    dest_engine: str,
    src_table: Table,
    dest_table: Table,
) -> int:
    dest_cols_by_name = {c.name: c for c in dest_table.columns}
    inserted = 0
    for src_col in src_table.columns:
        dest_col = dest_cols_by_name.get(src_col.name)
        dest_native = (
            dest_col.native_type
            if dest_col
            else default_dest_type(source_engine, src_col.native_type, src_col.normalized_type, dest_engine)
        )
        dest_norm = dest_col.normalized_type if dest_col else src_col.normalized_type
        db.add(
            Mapping(
                comparison_id=comparison_id,
                source_table=src_table.qualified_name,
                source_column=src_col.name,
                dest_table=dest_table.qualified_name,
                dest_column=src_col.name,
                source_type=src_col.native_type,
                default_dest_type=dest_native,
                override_dest_type=None,
                is_lossy=is_lossy(src_col.normalized_type, dest_norm),
                notes=None,
            )
        )
        inserted += 1
    return inserted
