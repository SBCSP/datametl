"""Strategy ABC. v1 ships a single concrete implementation: LogicalCopyStrategy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.transforms.column_plan import ColumnPlan


@dataclass
class TableMoveContext:
    source_table: str         # qualified, e.g. "public.posts"
    dest_table: str           # qualified
    column_plan: ColumnPlan
    conflict_mode: str        # "truncate" | "append" | "abort"
    skip_truncate: bool = False  # set by the runner when an upfront bulk TRUNCATE
                                  # already cleared this table — prevents a per-table
                                  # TRUNCATE … CASCADE from running and wiping any
                                  # already-loaded children whose parents the topo
                                  # sort placed later than they should have been.


@dataclass
class TableMoveResult:
    rows_read: int
    rows_written: int
    duration_ms: int
    detail: str = ""          # free-form notes (truncate skipped, etc.)


class Strategy(ABC):
    """Moves rows for one table from a source connection to a destination connection."""

    name: str

    @abstractmethod
    def run(self, src_engine, dst_engine, ctx: TableMoveContext) -> TableMoveResult: ...
