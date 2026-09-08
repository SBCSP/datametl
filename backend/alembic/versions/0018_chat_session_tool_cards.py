"""Persist Mel tool cards on chat sessions

Revision ID: 0018_chat_session_tool_cards
Revises: 0017_mel_tool_invocations
Create Date: 2026-09-08 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_chat_session_tool_cards"
down_revision: str | None = "0017_mel_tool_invocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "tool_cards",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "tool_cards")
