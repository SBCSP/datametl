"""Planner: turns a Comparison row + per-table user options into a structured MigrationPlan.

The plan is what the runner consumes. It's also persisted as JSONB on MigrationRun.plan
for reproducibility (re-runs replay the same plan; audits can answer "what was the
intent of this run").

Tables-only-in-source are surfaced as `skipped` with their qualified name and an attached
DDL preview the UI can show. Tables-only-in-destination are ignored (they keep their data;
we just don't write to them).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.introspection.normalized import Schema as NormalizedSchema
from app.migrations.ddl import full_ddl
from app.models.comparison import Comparison
from app.models.migration_run_table import ConflictMode

VerificationLevel = Literal["count_only", "count_and_sample", "count_sample_and_full_hash"]


class TableOption(BaseModel):
    """One row of user-provided options for a table-pair to migrate."""

    source_table: str  # qualified, e.g. "public.posts"
    dest_table: str    # qualified
    include: bool = True
    conflict_mode: ConflictMode = ConflictMode.truncate
    verification: VerificationLevel = "count_and_sample"


class TableOptionsPayload(BaseModel):
    """The wizard sends this in. `default_verification` is the level applied to any
    table not explicitly configured (used when we auto-fill the wizard from common_tables)."""

    tables: list[TableOption]
    default_verification: VerificationLevel = "count_and_sample"


@dataclass
class PlannedTable:
    source_table: str
    dest_table: str
    conflict_mode: ConflictMode
    verification: VerificationLevel


@dataclass
class SkippedTable:
    """Table only in source — not migrated. UI surfaces the DDL for the user to apply themselves."""

    source_table: str
    reason: str
    ddl_preview: str | None = None


@dataclass
class MigrationPlan:
    comparison_id: str
    source_schema: str | None
    dest_schema: str | None
    included: list[PlannedTable] = field(default_factory=list)
    skipped: list[SkippedTable] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        """Persistable form for MigrationRun.plan."""
        return {
            "comparison_id": self.comparison_id,
            "source_schema": self.source_schema,
            "dest_schema": self.dest_schema,
            "included": [
                {
                    "source_table": t.source_table,
                    "dest_table": t.dest_table,
                    "conflict_mode": t.conflict_mode.value,
                    "verification": t.verification,
                }
                for t in self.included
            ],
            "skipped": [
                {
                    "source_table": s.source_table,
                    "reason": s.reason,
                    "ddl_preview": s.ddl_preview,
                }
                for s in self.skipped
            ],
        }


def build_plan(
    cmp: Comparison,
    options: TableOptionsPayload,
    source_snapshot: NormalizedSchema,
) -> MigrationPlan:
    """Build a runnable plan.

    - Tables in `cmp.diff.common_tables` AND included by the user → `included`
    - Tables in `cmp.diff.tables_only_in_source` → `skipped` with DDL preview
    """
    diff = cmp.diff or {}
    common: set[str] = set()
    for t in diff.get("common_tables", []):
        # `t["table"]` may be either "public.posts" (same-schema) or "public.posts → legacy.posts"
        # (cross-schema). For matching against options, we prefer the user-supplied source_table.
        common.add(t.get("table", "").split(" → ")[0])

    only_src: list[str] = list(diff.get("tables_only_in_source", []))

    chosen = {(o.source_table, o.dest_table): o for o in options.tables if o.include}

    included: list[PlannedTable] = []
    for (src, dst), opt in chosen.items():
        included.append(
            PlannedTable(
                source_table=src,
                dest_table=dst,
                conflict_mode=opt.conflict_mode,
                verification=opt.verification,
            )
        )

    # For only-in-source tables, produce DDL preview so the UI can offer copy/paste SQL.
    src_tables_by_qn = {f"{t.schema_}.{t.name}": t for t in source_snapshot.tables}
    skipped: list[SkippedTable] = []
    for qn in only_src:
        tbl = src_tables_by_qn.get(qn)
        skipped.append(
            SkippedTable(
                source_table=qn,
                reason="Table does not exist on destination — v1 does not auto-CREATE.",
                ddl_preview=full_ddl(tbl) if tbl else None,
            )
        )

    return MigrationPlan(
        comparison_id=str(cmp.id),
        source_schema=cmp.source_schema,
        dest_schema=cmp.dest_schema,
        included=included,
        skipped=skipped,
    )
