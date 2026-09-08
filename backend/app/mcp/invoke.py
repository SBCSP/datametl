"""Shared Mel / FastMCP tool execution with approve-to-run + audit.

Mel chat streams NDJSON around this; external FastMCP calls it directly.
Both paths use the same Redis approval waiters and mel_tool_invocations rows.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.mcp import audit as mel_audit
from app.mcp import tools as mcp_tools
from app.mcp.approval import (
    MelApprovalRedisUnavailable,
    args_summary,
    needs_approval,
    outcome_summary,
    register_proposal,
    wait_decision,
)

# Marker stored in mel_tool_invocations.model for external FastMCP calls.
FASTMCP_MODEL = "fastmcp"


@dataclass(frozen=True)
class ToolInvokeResult:
    proposal_id: uuid.UUID
    result_json: str
    decision: str  # approved | denied | auto
    outcome: str  # success | error | denied
    outcome_detail: str
    denied: bool


def execute_tool(name: str, tool_input: dict[str, Any], engine: str, creds: dict[str, Any]) -> str:
    """Run one read-only MCP tool; errors become JSON payloads (never raise)."""
    try:
        if name == "list_tables":
            return mcp_tools.list_tables(engine, creds)
        if name == "describe_table":
            return mcp_tools.describe_table(
                engine,
                creds,
                str(tool_input.get("schema", "")),
                str(tool_input.get("table", "")),
            )
        if name == "run_sql":
            return mcp_tools.run_sql(engine, creds, str(tool_input.get("query", "")))
        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as e:  # tool errors come back as content, not exceptions
        return json.dumps({"error": str(e)})


async def invoke_db_tool(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    engine: str,
    creds: dict[str, Any],
    conn_id: uuid.UUID | None,
    conn_name: str | None,
    approval_mode: str,
    model: str | None = None,
    session_id: uuid.UUID | None = None,
    on_pending: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> ToolInvokeResult:
    """Approve-to-run (per settings mode) + audit + execute one DB tool.

    ``on_pending`` is optional (Mel chat uses it to emit tool_pending NDJSON).
    Raises MelApprovalRedisUnavailable when Redis cannot register/wait (fail closed).
    """
    proposal_id = uuid.uuid4()
    summary = args_summary(tool_name, tool_input)
    require = needs_approval(tool_name, approval_mode)

    if require:
        mel_audit.create_invocation(
            proposal_id=proposal_id,
            tool_name=tool_name,
            tool_input=tool_input,
            decision="pending",
            model=model,
            session_id=session_id,
            connection_id=conn_id,
            connection_name=conn_name,
        )
        await register_proposal(proposal_id)
        if on_pending is not None:
            await on_pending({
                "type": "tool_pending",
                "proposal_id": str(proposal_id),
                "name": tool_name,
                "args": tool_input,
                "args_summary": summary,
                "status": "pending",
            })
        decision = await wait_decision(proposal_id)
        if decision != "approve":
            denied_payload = json.dumps({
                "error": "Tool denied by operator — not executed.",
                "denied": True,
            })
            detail = outcome_summary(denied_payload, denied=True)
            mel_audit.finish_invocation(
                proposal_id,
                decision="denied",
                outcome="denied",
                outcome_detail=detail,
            )
            return ToolInvokeResult(
                proposal_id=proposal_id,
                result_json=denied_payload,
                decision="denied",
                outcome="denied",
                outcome_detail=detail,
                denied=True,
            )
        decision_label = "approved"
    else:
        decision_label = "auto"
        mel_audit.create_invocation(
            proposal_id=proposal_id,
            tool_name=tool_name,
            tool_input=tool_input,
            decision="auto",
            model=model,
            session_id=session_id,
            connection_id=conn_id,
            connection_name=conn_name,
        )
        if on_pending is not None:
            await on_pending({
                "type": "tool_pending",
                "proposal_id": str(proposal_id),
                "name": tool_name,
                "args": tool_input,
                "args_summary": summary,
                "status": "auto",
            })

    result = await asyncio.to_thread(execute_tool, tool_name, tool_input, engine, creds)
    err = None
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("error"):
            err = str(parsed["error"])
    except Exception:
        pass
    out_status = "error" if err else "success"
    detail = outcome_summary(result, error=err)
    mel_audit.finish_invocation(
        proposal_id,
        decision=decision_label,
        outcome=out_status,
        outcome_detail=detail,
    )
    return ToolInvokeResult(
        proposal_id=proposal_id,
        result_json=result,
        decision=decision_label,
        outcome=out_status,
        outcome_detail=detail,
        denied=False,
    )


__all__ = [
    "FASTMCP_MODEL",
    "MelApprovalRedisUnavailable",
    "ToolInvokeResult",
    "execute_tool",
    "invoke_db_tool",
]
