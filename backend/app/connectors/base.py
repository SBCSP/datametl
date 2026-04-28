from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.introspection.normalized import Schema


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
