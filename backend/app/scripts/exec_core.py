"""Shared per-connection fan-out for running a list of SQL statements.

Both the manual SQL Scripts run (`jobs.tasks.execute_sql_script`) and the scheduled run
(`jobs.tasks.run_scheduled_script`) use this so the execution semantics — per-connection
isolation, read-only vs commit, error shaping — are identical. The metadata DB session is
NOT touched here: callers decrypt credentials up front and hand over plain dicts, so the slow
sync SQL can run off the event loop in threads.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.connectors import for_engine
from app.scripts.runner import ROW_CAP, STATEMENT_TIMEOUT_S


def run_one(conn: dict[str, Any], statements: list[str], read_only: bool) -> dict[str, Any]:
    """Run `statements` against one decrypted connection dict (keys: id, name, engine, creds).

    Returns a connection-result dict: {connection_id, connection_name, ok, error, statements}.
    A connection-level failure (can't connect, etc.) is isolated into a single failed entry
    rather than raised, so one bad connection never aborts the whole fan-out.
    """
    if conn["engine"] is None:
        return {"connection_id": conn["id"], "connection_name": conn["name"], "ok": False,
                "error": "Connection not found", "statements": []}
    try:
        connector = for_engine(conn["engine"], conn["creds"])
        stmts = connector.run_statements(statements, ROW_CAP, STATEMENT_TIMEOUT_S, read_only)
        ok = all(s["error"] is None for s in stmts)
        return {"connection_id": conn["id"], "connection_name": conn["name"], "ok": ok,
                "error": None, "statements": stmts}
    except Exception as e:  # connection-level failure, isolate per connection
        # str(e.__cause__ or e) mirrors test_connection: surfaces the psycopg message
        # (host/port/db/user) without the password, which psycopg never includes.
        return {"connection_id": conn["id"], "connection_name": conn["name"], "ok": False,
                "error": str(getattr(e, "__cause__", None) or e), "statements": []}


async def run_against_connections(
    conns: list[dict[str, Any]], statements: list[str], read_only: bool
) -> list[dict[str, Any]]:
    """Fan `statements` out across every decrypted connection dict concurrently (one thread
    each) and gather the per-connection result dicts."""
    return list(
        await asyncio.gather(
            *[asyncio.to_thread(run_one, c, statements, read_only) for c in conns]
        )
    )
