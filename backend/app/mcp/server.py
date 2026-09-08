"""External FastMCP server — Pro-gated read-only DB tools with Mel approve-to-run + audit.

Mount the HTTP app at ``/mcp/external`` (see ``app.main``) or run stdio:

    cd backend && uv run python -m app.mcp.server

Tools bind to the active MCP connection (Settings / Connections → Activate MCP).
Community installs get HTTP 402 from the mount middleware; tool handlers also fail closed.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db import SessionLocal
from app.license.entitlements import get_entitlements
from app.license.gates import LICENSE_HTTP_STATUS
from app.mcp.invoke import FASTMCP_MODEL, MelApprovalRedisUnavailable, invoke_db_tool
from app.mcp.state import get_active_connection
from app.mcp.tools import NoActiveConnection, active_target
from app.settings_store import get_mel_tool_approval

logger = logging.getLogger(__name__)

EXTERNAL_MCP_FEATURE = "External MCP (FastMCP)"
COMMUNITY_EXTERNAL_MCP_LIMIT = (
    f"{EXTERNAL_MCP_FEATURE} requires DataMETL Pro. "
    "Activate a license key in Settings "
    "(or set DATAMETL_LICENSE_DEV_BYPASS=true for local docker). "
    "Community still includes in-app Mel with Approve-always."
)

mcp = FastMCP(
    name="DataMETL",
    instructions=(
        "Read-only database tools for the connection currently activated as the "
        "DataMETL MCP target. Writes/DDL are rejected. Some tools (especially run_sql) "
        "may wait for the operator to Approve or Deny in the DataMETL UI "
        "(POST /api/chat/tool-decision) before executing. Pro license required."
    ),
)


class ExternalMcpProMiddleware(BaseHTTPMiddleware):
    """Reject Community traffic to the FastMCP mount with HTTP 402."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        db = SessionLocal()
        try:
            ents = get_entitlements(db)
            if not ents.is_pro:
                return JSONResponse(
                    {"detail": COMMUNITY_EXTERNAL_MCP_LIMIT},
                    status_code=LICENSE_HTTP_STATUS,
                )
        finally:
            db.close()
        return await call_next(request)


def _require_pro_session() -> Any:
    """Open a short-lived Session and ensure Pro; caller must close."""
    db = SessionLocal()
    ents = get_entitlements(db)
    if not ents.is_pro:
        db.close()
        raise PermissionError(COMMUNITY_EXTERNAL_MCP_LIMIT)
    return db, ents


async def _run_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    try:
        db, ents = _require_pro_session()
    except PermissionError as e:
        return json.dumps({"error": str(e), "code": LICENSE_HTTP_STATUS})

    try:
        try:
            conn_name, engine, creds = active_target(db)
        except NoActiveConnection as e:
            return json.dumps({"error": str(e)})
        conn = get_active_connection(db)
        conn_id = conn.id if conn is not None else None
        approval_mode = ents.effective_mel_tool_approval(get_mel_tool_approval(db))
    finally:
        db.close()

    try:
        result = await invoke_db_tool(
            tool_name=tool_name,
            tool_input=tool_input,
            engine=engine,
            creds=creds,
            conn_id=conn_id,
            conn_name=conn_name,
            approval_mode=approval_mode,
            model=FASTMCP_MODEL,
            session_id=None,
        )
    except MelApprovalRedisUnavailable as e:
        logger.error("FastMCP tool blocked — Redis approval unavailable: %s", e)
        return json.dumps({"error": str(e), "denied": True})
    return result.result_json


@mcp.tool
async def list_tables() -> str:
    """List the user tables (schema and name) in the active DataMETL MCP database."""
    return await _run_tool("list_tables", {})


@mcp.tool
async def describe_table(schema: str, table: str) -> str:
    """Columns (name, data type, nullability, default) of one table on the active MCP DB."""
    return await _run_tool("describe_table", {"schema": schema, "table": table})


@mcp.tool
async def run_sql(query: str) -> str:
    """Run a read-only SQL query against the active MCP database (capped). May wait for Approve."""
    return await _run_tool("run_sql", {"query": query})


def create_http_app():
    """Starlette ASGI app for mounting under FastAPI (Pro middleware attached)."""
    app = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)
    app.add_middleware(ExternalMcpProMiddleware)
    return app


def main() -> None:
    """Stdio entry for Claude Desktop / Cursor MCP configs (still Pro-gated per tool)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
