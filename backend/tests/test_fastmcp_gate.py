"""External FastMCP: Pro gate + approve-to-run/audit path (no live Docker Redis)."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Match other license tests — control bypass explicitly.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.pop("DATAMETL_LICENSE_DEV_BYPASS", None)

from app.license.entitlements import Tier, get_entitlements
from app.license.gates import LICENSE_HTTP_STATUS, require_external_mcp
from app.mcp.approval import APPROVAL_AUTO, APPROVAL_RUN_SQL_ONLY, set_redis_client_for_tests
from app.mcp.invoke import FASTMCP_MODEL, invoke_db_tool
from app.mcp.server import COMMUNITY_EXTERNAL_MCP_LIMIT, ExternalMcpProMiddleware
from tests.test_mel_approval import FakeAsyncRedis


@pytest.fixture()
def fake_redis():
    client = FakeAsyncRedis()
    set_redis_client_for_tests(client)
    yield client
    set_redis_client_for_tests(None)


def test_community_disallows_external_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)
    ents = get_entitlements(db=None)
    assert ents.tier == Tier.community
    assert ents.allows_external_mcp() is False


def test_pro_bypass_allows_external_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", True)
    ents = get_entitlements(db=None)
    assert ents.is_pro
    assert ents.allows_external_mcp() is True


def test_require_external_mcp_402_on_community(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)
    db = MagicMock()
    with patch("app.license.gates.get_entitlements", return_value=get_entitlements(db=None)):
        with pytest.raises(HTTPException) as ei:
            require_external_mcp(db)
    assert ei.value.status_code == LICENSE_HTTP_STATUS
    assert "External MCP" in str(ei.value.detail) or "Pro" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_pro_middleware_rejects_community(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)

    class _FakeSession:
        def close(self) -> None:
            return None

    async def boom(_request: Request) -> Response:
        return Response("should-not-run", status_code=200)

    with patch("app.mcp.server.SessionLocal", return_value=_FakeSession()):
        with patch("app.mcp.server.get_entitlements", return_value=get_entitlements(db=None)):
            mw = ExternalMcpProMiddleware(app=boom)
            req = Request({"type": "http", "method": "POST", "path": "/mcp", "headers": []})
            resp = await mw.dispatch(req, boom)
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == LICENSE_HTTP_STATUS
    body = json.loads(resp.body.decode())
    assert "Pro" in body["detail"]
    assert COMMUNITY_EXTERNAL_MCP_LIMIT


@pytest.mark.asyncio
async def test_invoke_auto_audits_without_approval(fake_redis: FakeAsyncRedis) -> None:
    created: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []

    def _create(**kwargs: Any) -> MagicMock:
        created.append(kwargs)
        return MagicMock()

    def _finish(proposal_id: uuid.UUID, **kwargs: Any) -> None:
        finished.append({"proposal_id": proposal_id, **kwargs})

    with (
        patch("app.mcp.invoke.mel_audit.create_invocation", side_effect=_create),
        patch("app.mcp.invoke.mel_audit.finish_invocation", side_effect=_finish),
        patch(
            "app.mcp.invoke.execute_tool",
            return_value=json.dumps({"tables": [], "count": 0}),
        ),
    ):
        result = await invoke_db_tool(
            tool_name="list_tables",
            tool_input={},
            engine="postgres",
            creds={},
            conn_id=uuid.uuid4(),
            conn_name="demo",
            approval_mode=APPROVAL_AUTO,
            model=FASTMCP_MODEL,
        )
    assert result.denied is False
    assert result.decision == "auto"
    assert result.outcome == "success"
    assert created[0]["decision"] == "auto"
    assert created[0]["model"] == FASTMCP_MODEL
    assert finished[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_invoke_run_sql_waits_and_denies(fake_redis: FakeAsyncRedis) -> None:
    import asyncio

    from app.mcp.approval import resolve_decision

    created: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []
    pending_events: list[dict[str, Any]] = []

    def _create(**kwargs: Any) -> MagicMock:
        created.append(kwargs)
        return MagicMock()

    def _finish(proposal_id: uuid.UUID, **kwargs: Any) -> None:
        finished.append({"proposal_id": proposal_id, **kwargs})

    async def _on_pending(evt: dict[str, Any]) -> None:
        pending_events.append(evt)
        pid = uuid.UUID(evt["proposal_id"])

        async def _deny() -> None:
            await asyncio.sleep(0.05)
            assert await resolve_decision(pid, "deny")

        asyncio.create_task(_deny())

    with (
        patch("app.mcp.invoke.mel_audit.create_invocation", side_effect=_create),
        patch("app.mcp.invoke.mel_audit.finish_invocation", side_effect=_finish),
        patch("app.mcp.invoke.execute_tool") as exec_tool,
    ):
        result = await invoke_db_tool(
            tool_name="run_sql",
            tool_input={"query": "SELECT 1"},
            engine="postgres",
            creds={},
            conn_id=None,
            conn_name="demo",
            approval_mode=APPROVAL_RUN_SQL_ONLY,
            model=FASTMCP_MODEL,
            on_pending=_on_pending,
        )
    assert result.denied is True
    assert result.decision == "denied"
    assert result.outcome == "denied"
    assert created[0]["decision"] == "pending"
    assert pending_events and pending_events[0]["status"] == "pending"
    exec_tool.assert_not_called()
    data = json.loads(result.result_json)
    assert data.get("denied") is True


@pytest.mark.asyncio
async def test_invoke_run_sql_approve_then_execute(fake_redis: FakeAsyncRedis) -> None:
    import asyncio

    from app.mcp.approval import resolve_decision

    finished: list[dict[str, Any]] = []

    def _finish(proposal_id: uuid.UUID, **kwargs: Any) -> None:
        finished.append({"proposal_id": proposal_id, **kwargs})

    proposal_box: dict[str, uuid.UUID] = {}

    async def _on_pending(evt: dict[str, Any]) -> None:
        proposal_box["id"] = uuid.UUID(evt["proposal_id"])

        async def _approve() -> None:
            await asyncio.sleep(0.05)
            assert await resolve_decision(proposal_box["id"], "approve")

        asyncio.create_task(_approve())

    with (
        patch("app.mcp.invoke.mel_audit.create_invocation", return_value=MagicMock()),
        patch("app.mcp.invoke.mel_audit.finish_invocation", side_effect=_finish),
        patch(
            "app.mcp.invoke.execute_tool",
            return_value=json.dumps({"columns": ["x"], "rows": [[1]], "row_count": 1}),
        ) as exec_tool,
    ):
        result = await invoke_db_tool(
            tool_name="run_sql",
            tool_input={"query": "SELECT 1"},
            engine="postgres",
            creds={},
            conn_id=uuid.uuid4(),
            conn_name="demo",
            approval_mode=APPROVAL_RUN_SQL_ONLY,
            model=FASTMCP_MODEL,
            on_pending=_on_pending,
        )
    assert result.denied is False
    assert result.decision == "approved"
    assert result.outcome == "success"
    exec_tool.assert_called_once()
    assert finished[-1]["decision"] == "approved"
