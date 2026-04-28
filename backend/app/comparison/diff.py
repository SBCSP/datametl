"""Pure schema diff. Produces structured output the API/frontend can render side-by-side."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.introspection.normalized import Column, Schema, Table

ColumnDriftKind = Literal[
    "type_changed",
    "nullable_changed",
    "default_changed",
    "pk_changed",
    "fk_changed",
    "missing_in_dest",
    "missing_in_source",
]


class ColumnDrift(BaseModel):
    table: str
    column: str
    kind: ColumnDriftKind
    source: str | None = None
    dest: str | None = None


class TableComparison(BaseModel):
    table: str  # The display name. With schema scope = "{source_schema}.{name}"
    column_drift: list[ColumnDrift]


class SchemaDiff(BaseModel):
    tables_only_in_source: list[str]
    tables_only_in_dest: list[str]
    common_tables: list[TableComparison]


def diff_schemas(
    source: Schema,
    dest: Schema,
    *,
    source_schema: str | None = None,
    dest_schema: str | None = None,
) -> SchemaDiff:
    """Diff two snapshots.

    Default: compares every table by qualified name (`schema.table`) — works when both
    snapshots have the same schema layout (e.g. `public` on both sides).

    Schema-scoped: when both `source_schema` and `dest_schema` are provided, only tables
    in those schemas are considered, and they're matched on bare table name. This handles
    cross-schema migration plans like `prod.public` → `staging.legacy_data`.
    """
    if source_schema is not None and dest_schema is not None:
        return _diff_scoped(source, dest, source_schema, dest_schema)

    src_tables = {t.qualified_name: t for t in source.tables}
    dst_tables = {t.qualified_name: t for t in dest.tables}

    only_src = sorted(set(src_tables) - set(dst_tables))
    only_dst = sorted(set(dst_tables) - set(src_tables))
    common = sorted(set(src_tables) & set(dst_tables))

    return SchemaDiff(
        tables_only_in_source=only_src,
        tables_only_in_dest=only_dst,
        common_tables=[
            TableComparison(table=t, column_drift=_diff_table(src_tables[t], dst_tables[t], display=t))
            for t in common
        ],
    )


def _diff_scoped(source: Schema, dest: Schema, src_sch: str, dst_sch: str) -> SchemaDiff:
    src = {t.name: t for t in source.tables if t.schema_ == src_sch}
    dst = {t.name: t for t in dest.tables if t.schema_ == dst_sch}

    only_src = sorted(set(src) - set(dst))
    only_dst = sorted(set(dst) - set(src))
    common = sorted(set(src) & set(dst))

    return SchemaDiff(
        # Display only-in lists with their schema prefix so users can copy/paste fully-qualified names.
        tables_only_in_source=[f"{src_sch}.{n}" for n in only_src],
        tables_only_in_dest=[f"{dst_sch}.{n}" for n in only_dst],
        common_tables=[
            TableComparison(
                # When schemas differ, show "src_schema.name → dst_schema.name" so the report is unambiguous.
                table=f"{src_sch}.{n}" if src_sch == dst_sch else f"{src_sch}.{n} → {dst_sch}.{n}",
                column_drift=_diff_table(src[n], dst[n], display=f"{src_sch}.{n}"),
            )
            for n in common
        ],
    )


def _diff_table(src: Table, dst: Table, *, display: str) -> list[ColumnDrift]:
    src_cols = {c.name: c for c in src.columns}
    dst_cols = {c.name: c for c in dst.columns}

    drift: list[ColumnDrift] = []

    for name in sorted(set(src_cols) - set(dst_cols)):
        drift.append(ColumnDrift(table=display, column=name, kind="missing_in_dest"))
    for name in sorted(set(dst_cols) - set(src_cols)):
        drift.append(ColumnDrift(table=display, column=name, kind="missing_in_source"))

    for name in sorted(set(src_cols) & set(dst_cols)):
        s = src_cols[name]
        d = dst_cols[name]
        drift.extend(_compare_column(display, name, s, d))

    return drift


def _compare_column(table: str, name: str, s: Column, d: Column) -> list[ColumnDrift]:
    out: list[ColumnDrift] = []
    if s.native_type != d.native_type or s.normalized_type != d.normalized_type:
        out.append(
            ColumnDrift(
                table=table, column=name, kind="type_changed",
                source=f"{s.native_type} ({s.normalized_type})",
                dest=f"{d.native_type} ({d.normalized_type})",
            )
        )
    if s.nullable != d.nullable:
        out.append(
            ColumnDrift(
                table=table, column=name, kind="nullable_changed",
                source=str(s.nullable), dest=str(d.nullable),
            )
        )
    if s.default != d.default:
        out.append(
            ColumnDrift(
                table=table, column=name, kind="default_changed",
                source=s.default, dest=d.default,
            )
        )
    if s.is_primary_key != d.is_primary_key:
        out.append(
            ColumnDrift(
                table=table, column=name, kind="pk_changed",
                source=str(s.is_primary_key), dest=str(d.is_primary_key),
            )
        )
    if (s.foreign_key is None) != (d.foreign_key is None) or (
        s.foreign_key and d.foreign_key and s.foreign_key.model_dump() != d.foreign_key.model_dump()
    ):
        out.append(
            ColumnDrift(
                table=table, column=name, kind="fk_changed",
                source=s.foreign_key.model_dump_json() if s.foreign_key else None,
                dest=d.foreign_key.model_dump_json() if d.foreign_key else None,
            )
        )
    return out
