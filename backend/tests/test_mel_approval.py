"""Mel tool approval helpers + in-process Approve/Deny waiters (no DB)."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.mcp.approval import (
    APPROVAL_ALWAYS,
    APPROVAL_AUTO,
    APPROVAL_RUN_SQL_ONLY,
    args_summary,
    clear_all_pending,
    needs_approval,
    outcome_summary,
    redact_args,
    register_proposal,
    resolve_decision,
    wait_decision,
)


def test_needs_approval_run_sql_only_default() -> None:
    assert needs_approval("run_sql", APPROVAL_RUN_SQL_ONLY) is True
    assert needs_approval("list_tables", APPROVAL_RUN_SQL_ONLY) is False
    assert needs_approval("describe_table", APPROVAL_RUN_SQL_ONLY) is False


def test_needs_approval_always_and_auto() -> None:
    assert needs_approval("list_tables", APPROVAL_ALWAYS) is True
    assert needs_approval("run_sql", APPROVAL_ALWAYS) is True
    assert needs_approval("run_sql", APPROVAL_AUTO) is False
    assert needs_approval("list_tables", APPROVAL_AUTO) is False


def test_redact_args_strips_secrets_and_truncates() -> None:
    red = redact_args({
        "query": "SELECT 1",
        "password": "super-secret",
        "api_key": "sk-ant-xxx",
        "nested": {"token": "abc", "ok": 1},
        "long": "x" * 5000,
    })
    assert red["query"] == "SELECT 1"
    assert red["password"] == "[redacted]"
    assert red["api_key"] == "[redacted]"
    assert red["nested"]["token"] == "[redacted]"
    assert red["nested"]["ok"] == 1
    assert red["long"].endswith("…")
    assert len(red["long"]) == 4001


def test_args_summary_shapes() -> None:
    assert args_summary("list_tables", {}) == "list tables"
    assert "public.users" in args_summary("describe_table", {"schema": "public", "table": "users"})
    assert "SELECT" in args_summary("run_sql", {"query": "SELECT 1"})


def test_outcome_summary_denied_and_rows() -> None:
    assert "Denied" in outcome_summary("{}", denied=True)
    assert "2 rows" in outcome_summary('{"columns":["a"],"rows":[[1],[2]],"row_count":2}')


@pytest.mark.asyncio
async def test_approve_deny_happy_paths() -> None:
    clear_all_pending()
    pid = uuid.uuid4()
    await register_proposal(pid)

    async def approve_soon() -> None:
        await asyncio.sleep(0.05)
        assert resolve_decision(pid, "approve") is True

    task = asyncio.create_task(approve_soon())
    assert await wait_decision(pid, timeout=2.0) == "approve"
    await task

    pid2 = uuid.uuid4()
    await register_proposal(pid2)

    async def deny_soon() -> None:
        await asyncio.sleep(0.05)
        assert resolve_decision(pid2, "deny") is True

    task2 = asyncio.create_task(deny_soon())
    assert await wait_decision(pid2, timeout=2.0) == "deny"
    await task2

    # Already decided → resolve returns False
    assert resolve_decision(pid2, "approve") is False
    clear_all_pending()


@pytest.mark.asyncio
async def test_denied_tools_do_not_look_like_success() -> None:
    """Contract used by the tool loop: denied payload is an error the model must honor."""
    import json

    denied = json.dumps({"error": "Tool denied by operator — not executed.", "denied": True})
    data = json.loads(denied)
    assert data.get("denied") is True
    assert "not executed" in data["error"].lower()
