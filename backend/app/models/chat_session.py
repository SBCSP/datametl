from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ChatSession(Base):
    """A saved Mel conversation.

    `messages` is the chat transcript ({role, content}[]).
    `tool_cards` is a UI sidecar for Mel Approve/Deny cards so reloading a session
    still shows pending/approved/denied/error tool proposals (not only live NDJSON).
    The Mel audit table remains the source of truth for activity/compliance.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New chat")
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    tool_cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
