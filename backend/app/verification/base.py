"""Verification framework — runs after data movement to prove the migration was correct.

Each check is a small focused class with `run(src_engine, dst_engine, ctx)`. Results are
serialized to JSONB on `migration_run_tables.verification` so the UI can render badge clusters
(count ✓ / sample ✓ / sequence ✓) and drill-down details.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckContext:
    source_table: str       # qualified
    dest_table: str         # qualified


@dataclass
class CheckResult:
    name: str               # e.g. "row_count"
    passed: bool
    detail: str             # one-line summary, shown in the UI
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # populated if the check itself raised

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "metrics": self.metrics,
            "error": self.error,
        }


class Check(ABC):
    name: str

    @abstractmethod
    def run(self, src_engine, dst_engine, ctx: CheckContext) -> CheckResult: ...
