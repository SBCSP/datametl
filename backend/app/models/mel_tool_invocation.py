"""Audit log for Mel (in-app chat) tool invocations against the active MCP connection."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class MelToolInvocation(Base):
    """One Mel tool call — proposed, approved/denied/auto-run, and its outcome.

    Args are stored redacted (secrets stripped). Used by the activity feed and Mel audit API.
    """

    __tablename__ = "mel_tool_invocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Chat session may not exist yet when the stream starts (first message of a new chat).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    args_summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    # pending | approved | denied | auto
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # pending | success | error | denied | cancelled | timeout
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True, default=uuid.uuid4
    )
