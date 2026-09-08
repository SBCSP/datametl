"""Mel tool audit persistence helpers — mocked Session (no real DB)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.mcp import audit as mel_audit
from app.models.mel_tool_invocation import MelToolInvocation


def test_create_invocation_redacts_and_commits() -> None:
    db = MagicMock()
    # refresh/expunge no-ops; commit recorded
    proposal = uuid.uuid4()
    row = mel_audit.create_invocation(
        proposal_id=proposal,
        tool_name="run_sql",
        tool_input={"query": "SELECT 1", "password": "nope"},
        decision="pending",
        model="claude-opus-4-8",
        session_id=None,
        connection_id=None,
        connection_name="prod",
        db=db,
    )
    assert isinstance(row, MelToolInvocation)
    assert row.tool_name == "run_sql"
    assert row.args_redacted.get("password") == "[redacted]"
    assert row.args_redacted.get("query") == "SELECT 1"
    assert "SELECT" in row.args_summary
    db.add.assert_called_once()
    db.commit.assert_called()
    db.refresh.assert_called()


def test_finish_invocation_sets_outcome() -> None:
    db = MagicMock()
    proposal = uuid.uuid4()
    existing = MelToolInvocation(
        proposal_id=proposal,
        tool_name="run_sql",
        args_redacted={"query": "SELECT 1"},
        args_summary="SELECT 1",
        decision="pending",
        outcome="pending",
    )
    db.execute.return_value.scalar_one_or_none.return_value = existing
    mel_audit.finish_invocation(
        proposal,
        decision="denied",
        outcome="denied",
        outcome_detail="Denied by operator — not executed",
        db=db,
    )
    assert existing.decision == "denied"
    assert existing.outcome == "denied"
    assert existing.finished_at is not None
    db.commit.assert_called()
