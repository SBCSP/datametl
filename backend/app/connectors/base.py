from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.introspection.normalized import Schema
from app.scripts.runner import StatementResult


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    detail: str


class Connector(ABC):
    """Abstract connector to a user-supplied database.

    Phase 1 implementations only need `test_connection` and `introspect`. Phase 2 will add
    `read_rows` / `write_rows` (or strategies will subclass directly — TBD).
    """

    engine: str

    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult: ...

    @abstractmethod
    def introspect(self) -> Schema: ...

    @abstractmethod
    def run_readonly_statements(
        self, statements: list[str], row_cap: int, timeout_s: int
    ) -> list[StatementResult]:
        """Execute `statements` in a single read-only transaction and roll it back.

        Returns one StatementResult per statement attempted. Errors (including read-only
        violations) are captured per statement, not raised; execution stops at the first
        erroring statement. Implementations MUST NOT write to the database, and MUST NOT put
        credentials / the DSN into any error string.
        """
        ...
