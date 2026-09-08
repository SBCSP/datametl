"""Mel tool approval: which tools need operator confirm, and in-flight proposal waiters.

Pending proposals live in-process (single uvicorn worker is the local-first default). The chat
stream emits a `tool_pending` event, then awaits the Future until the UI POSTs approve/deny.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

# Tools Mel may call against the active read-only MCP connection.
MEL_TOOLS = frozenset({"list_tables", "describe_table", "run_sql"})

# Settings values for mel_tool_approval.
APPROVAL_RUN_SQL_ONLY = "run_sql_only"  # default — SQL still needs a human click
APPROVAL_ALWAYS = "always"
APPROVAL_AUTO = "auto"
APPROVAL_MODES = frozenset({APPROVAL_RUN_SQL_ONLY, APPROVAL_ALWAYS, APPROVAL_AUTO})
DEFAULT_APPROVAL_MODE = APPROVAL_RUN_SQL_ONLY

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)

# proposal_id (str) → Future that resolves to "approve" | "deny"
_pending: dict[str, asyncio.Future[str]] = {}
_lock = asyncio.Lock()

APPROVAL_TIMEOUT_S = 300.0  # 5 minutes — operator walked away


def needs_approval(tool_name: str, mode: str) -> bool:
    """Whether this tool must wait for Approve/Deny under the given settings mode."""
    if mode == APPROVAL_AUTO:
        return False
    if mode == APPROVAL_ALWAYS:
        return tool_name in MEL_TOOLS
    # run_sql_only (default) — safer for the tool that actually runs operator SQL
    return tool_name == "run_sql"


def redact_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Copy tool args for audit storage, stripping secret-looking keys and truncating long strings."""
    if not args:
        return {}
    out: dict[str, Any] = {}
    for key, value in args.items():
        k = str(key)
        if _SECRET_KEY_RE.search(k):
            out[k] = "[redacted]"
        elif isinstance(value, dict):
            out[k] = redact_args(value)
        elif isinstance(value, str):
            out[k] = value if len(value) <= 4000 else value[:4000] + "…"
        else:
            out[k] = value
    return out


def args_summary(tool_name: str, args: dict[str, Any] | None) -> str:
    """Short one-line summary for the chat Approve/Deny card and activity feed."""
    args = args or {}
    if tool_name == "list_tables":
        return "list tables"
    if tool_name == "describe_table":
        schema = str(args.get("schema") or "")
        table = str(args.get("table") or "")
        return f"describe {schema}.{table}".strip(".")
    if tool_name == "run_sql":
        q = " ".join(str(args.get("query") or "").split())
        if not q:
            return "run_sql (empty)"
        return q if len(q) <= 140 else q[:140] + "…"
    try:
        raw = json.dumps(args, default=str)
    except Exception:
        raw = str(args)
    return raw if len(raw) <= 140 else raw[:140] + "…"


def outcome_summary(result_json: str, *, denied: bool = False, error: str | None = None) -> str:
    if denied:
        return "Denied by operator — not executed"
    if error:
        return f"Error: {error[:200]}"
    try:
        data = json.loads(result_json)
    except Exception:
        return (result_json or "")[:160]
    if isinstance(data, dict):
        if data.get("error"):
            return f"Error: {str(data['error'])[:200]}"
        if "tables" in data and "count" in data:
            return f"{data['count']} tables"
        if "columns" in data and "row_count" in data:
            n = data.get("row_count", 0)
            trunc = " (truncated)" if data.get("truncated") else ""
            return f"{n} row{'s' if n != 1 else ''}{trunc}"
        if "row_count" in data:
            n = data.get("row_count", 0)
            trunc = " (truncated)" if data.get("truncated") else ""
            return f"{n} row{'s' if n != 1 else ''}{trunc}"
    return "ok"


async def register_proposal(proposal_id: uuid.UUID | str) -> asyncio.Future[str]:
    """Create a waiter Future for this proposal (call before emitting tool_pending)."""
    key = str(proposal_id)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    async with _lock:
        old = _pending.pop(key, None)
        if old is not None and not old.done():
            old.set_result("deny")  # replace stale
        _pending[key] = fut
    return fut


async def wait_decision(proposal_id: uuid.UUID | str, timeout: float = APPROVAL_TIMEOUT_S) -> str:
    """Block until Approve/Deny (or timeout → deny). Cleans up the waiter."""
    key = str(proposal_id)
    async with _lock:
        fut = _pending.get(key)
    if fut is None:
        fut = await register_proposal(proposal_id)
    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
    except TimeoutError:
        resolve_decision(proposal_id, "deny")
        return "deny"
    finally:
        async with _lock:
            _pending.pop(key, None)


def resolve_decision(proposal_id: uuid.UUID | str, decision: str) -> bool:
    """Called by the Approve/Deny API. Returns False if no pending proposal."""
    if decision not in ("approve", "deny"):
        return False
    key = str(proposal_id)
    fut = _pending.get(key)
    if fut is None or fut.done():
        return False
    fut.set_result(decision)
    return True


def clear_all_pending() -> None:
    """Test helper — cancel every waiter."""
    for fut in list(_pending.values()):
        if not fut.done():
            fut.set_result("deny")
    _pending.clear()
