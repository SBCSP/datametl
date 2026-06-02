"""Pure helpers for the SQL script runner.

Kept free of any DB / connector imports so they're cheap to unit-test. The actual read-only
execution lives in the connector layer (`PostgresConnector.run_readonly_statements`) because the
read-only transaction SQL is engine-specific; this module only handles statement splitting and
the row-cap / result shaping that the connector reuses.
"""
from __future__ import annotations

from typing import Any, TypedDict

import sqlparse

# Default per-statement, per-connection row cap. The connector fetches cap+1 rows so it can
# tell the UI whether the result was truncated.
ROW_CAP = 1000

# Default per-statement timeout (seconds) — a runaway query on one connection shouldn't hang
# the whole fan-out.
STATEMENT_TIMEOUT_S = 30


class StatementResult(TypedDict):
    """Outcome of a single statement on a single connection."""

    index: int
    sql: str
    kind: str  # "rows" (returned a result set) | "command" (status only) | "error"
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    error: str | None


def split_statements(content: str) -> list[str]:
    """Split a script into individual executable statements.

    Uses sqlparse rather than a naive `content.split(";")` so semicolons inside string
    literals, dollar-quoted bodies, and comments don't wrongly break a statement. Empty and
    comment-only fragments are dropped, and the trailing separator semicolon is stripped.
    """
    statements: list[str] = []
    for raw in sqlparse.split(content or ""):
        stmt = raw.strip().rstrip(";").strip()
        if not stmt:
            continue
        # Skip fragments that are nothing but comments/whitespace.
        if not sqlparse.format(stmt, strip_comments=True).strip():
            continue
        statements.append(stmt)
    return statements


def cap_rows(rows: list[Any], cap: int) -> tuple[list[Any], bool]:
    """Trim `rows` to at most `cap` items, reporting whether anything was dropped.

    The caller fetches `cap + 1` rows so that "exactly cap fetched" is distinguishable from
    "more than cap available" — hence `len(rows) > cap` rather than `>=`.
    """
    return rows[:cap], len(rows) > cap
