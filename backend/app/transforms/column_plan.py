"""Resolve a per-column plan from a list of Mapping rows.

The output is everything the COPY strategy needs to assemble its SQL:

  * `select_exprs` — list of SELECT expressions on the source side, e.g.
       ['"id"', '"title"::varchar(100) AS "title"', '"author_id" AS "user_id"']
  * `dest_columns` — parallel list of destination column names (quoted), e.g.
       ['"id"', '"title"', '"user_id"']

The strategy then issues:

  COPY (SELECT {select_exprs} FROM {src_table}) TO STDOUT (FORMAT BINARY)
  COPY {dst_table} ({dst_columns}) FROM STDIN (FORMAT BINARY)

Three things this function handles:
  1. **Skip column**  — `mapping.skip = True` → omitted from both lists.
  2. **Type cast**    — when `effective_dest_type` differs from `source_type`, a `::dest_type` cast is added.
  3. **Column rename** — when `dest_column != source_column`, the SELECT alias = dest_column.

Mappings where source_column or dest_column is empty / nameless are skipped defensively.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models.mapping import Mapping


def _quote(ident: str) -> str:
    """Postgres identifier quoting — doubles any embedded quotes."""
    return '"' + ident.replace('"', '""') + '"'


@dataclass(frozen=True)
class ColumnPlan:
    select_exprs: list[str]   # source-side SELECT expressions, in order
    dest_columns: list[str]   # destination column names (quoted), parallel
    skipped: list[str]        # source columns deliberately skipped (for logging / preview)


def build_column_plan(mappings: Iterable[Mapping]) -> ColumnPlan:
    select_exprs: list[str] = []
    dest_columns: list[str] = []
    skipped: list[str] = []

    for m in mappings:
        if m.skip:
            skipped.append(m.source_column)
            continue
        if not m.source_column or not m.dest_column:
            skipped.append(m.source_column or "(unnamed)")
            continue

        src = _quote(m.source_column)
        dst = _quote(m.dest_column)
        eff = (m.override_dest_type or m.default_dest_type or "").strip()
        src_type = (m.source_type or "").strip()

        # Cast only when the effective destination type really differs from source. Comparison
        # is by exact native string — same as introspection captures it. Same-engine identity
        # (e.g. "varchar(255)" → "varchar(255)") emits no cast.
        if eff and eff != src_type:
            expr = f"({src})::{eff}"
        else:
            expr = src

        # Alias only when the destination column name differs.
        if m.dest_column != m.source_column:
            expr = f"{expr} AS {dst}"

        select_exprs.append(expr)
        dest_columns.append(dst)

    return ColumnPlan(select_exprs=select_exprs, dest_columns=dest_columns, skipped=skipped)
