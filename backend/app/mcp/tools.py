"""Read-only database tools bound to the active MCP connection.

The same three tools are surfaced two ways: to Mel (in-app chat, via Anthropic tool use) and to
external MCP clients (FastMCP server). All execution goes through the connector's read-only path
(`run_statements(read_only=True)`), so it inherits the read-only transaction, row cap, and
statement timeout — writes/DDL are rejected.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.connectors import for_engine
from app.crypto import vault
from app.mcp.state import get_active_connection
from app.scripts.runner import StatementResult

# Smaller cap than the SQL Scripts page — these results land in an LLM context window.
TOOL_ROW_CAP = 200
TOOL_TIMEOUT_S = 30

_SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast", "mysql", "performance_schema", "sys"}


class NoActiveConnection(Exception):
    pass


def active_target(db: Session) -> tuple[str, str, dict[str, Any]]:
    """(connection_name, engine, decrypted_creds) for the active connection, or raise."""
    conn = get_active_connection(db)
    if conn is None:
        raise NoActiveConnection("No active MCP connection. Activate one in DataMETL first.")
    return conn.name, conn.engine, vault.decrypt(conn.encrypted_credentials)


def _lit(value: str) -> str:
    """Escape a string for inlining as a SQL literal (read-only, but stay tidy)."""
    return value.replace("'", "''")


def _run(engine: str, creds: dict[str, Any], statements: list[str]) -> list[StatementResult]:
    return for_engine(engine, creds).run_statements(
        statements, TOOL_ROW_CAP, TOOL_TIMEOUT_S, read_only=True
    )


def _format(results: list[StatementResult]) -> str:
    """Compact, model-friendly JSON for one-or-more statement results."""
    out: list[dict[str, Any]] = []
    for r in results:
        if r["error"]:
            out.append({"error": r["error"], "sql": r["sql"]})
        elif r["kind"] == "rows":
            out.append({
                "columns": r["columns"], "rows": r["rows"],
                "row_count": r["row_count"], "truncated": r["truncated"],
            })
        else:
            out.append({"status": "ok", "rows_affected": r["row_count"]})
    payload = out[0] if len(out) == 1 else out
    return json.dumps(payload, default=str)


# --- the three tools (engine + creds resolved by the caller) ---

def list_tables(engine: str, creds: dict[str, Any]) -> str:
    """List user tables (schema + name) in the active database."""
    res = _run(engine, creds, [
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_type = 'BASE TABLE'"
    ])
    if res and res[0]["kind"] == "rows":
        tables = [
            {"schema": row[0], "table": row[1]}
            for row in res[0]["rows"]
            if row[0] not in _SYSTEM_SCHEMAS
        ]
        return json.dumps({"tables": tables, "count": len(tables)}, default=str)
    return _format(res)


def describe_table(engine: str, creds: dict[str, Any], schema: str, table: str) -> str:
    """Columns (name, type, nullable, default) of one table."""
    res = _run(engine, creds, [
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{_lit(schema)}' AND table_name = '{_lit(table)}' "
        "ORDER BY ordinal_position"
    ])
    return _format(res)


def run_sql(engine: str, creds: dict[str, Any], query: str) -> str:
    """Run a read-only SQL query and return the rows (capped). Writes/DDL are rejected."""
    return _format(_run(engine, creds, [query]))
