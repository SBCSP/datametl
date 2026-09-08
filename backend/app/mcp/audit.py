"""Persist Mel tool invocations for the activity / Mel audit surfaces."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.mcp.approval import args_summary, redact_args
from app.models.mel_tool_invocation import MelToolInvocation


def create_invocation(
    *,
    proposal_id: uuid.UUID,
    tool_name: str,
    tool_input: dict[str, Any],
    decision: str,
    model: str | None,
    session_id: uuid.UUID | None,
    connection_id: uuid.UUID | None,
    connection_name: str | None,
    db: Session | None = None,
) -> MelToolInvocation:
    """Insert a pending/auto row. Commits when managing its own session."""
    own = db is None
    session = db or SessionLocal()
    try:
        row = MelToolInvocation(
            proposal_id=proposal_id,
            tool_name=tool_name,
            args_redacted=redact_args(tool_input),
            args_summary=args_summary(tool_name, tool_input)[:512],
            decision=decision,
            outcome="pending",
            model=model,
            session_id=session_id,
            connection_id=connection_id,
            connection_name=connection_name,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row
    finally:
        if own:
            session.close()


def finish_invocation(
    proposal_id: uuid.UUID,
    *,
    decision: str | None = None,
    outcome: str,
    outcome_detail: str | None = None,
    db: Session | None = None,
) -> None:
    own = db is None
    session = db or SessionLocal()
    try:
        row = session.execute(
            select(MelToolInvocation).where(MelToolInvocation.proposal_id == proposal_id)
        ).scalar_one_or_none()
        if row is None:
            return
        if decision is not None:
            row.decision = decision
        row.outcome = outcome
        row.outcome_detail = (outcome_detail or "")[:2000] or None
        row.finished_at = datetime.now(UTC)
        session.commit()
    finally:
        if own:
            session.close()
