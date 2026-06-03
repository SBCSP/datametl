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
    def run_statements(
        self, statements: list[str], row_cap: int, timeout_s: int, read_only: bool
    ) -> list[StatementResult]:
        """Execute `statements` as a single transaction (atomic per connection).

        Returns one StatementResult per statement attempted; errors are captured per statement,
        not raised, and execution stops at the first error. When `read_only` is True the
        transaction is locked read-only and always rolled back. When False, the transaction
        commits only if every statement succeeds; any error rolls the whole script back.
        Implementations MUST NOT put credentials / the DSN into any error string.
        """
        ...
