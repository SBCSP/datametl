"""Mel tool invocation audit log

Revision ID: 0017_mel_tool_invocations
Revises: 0016_schedule_taps
Create Date: 2026-09-08 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_mel_tool_invocations"
down_revision: Union[str, None] = "0016_schedule_taps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mel_tool_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_name", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("args_summary", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("decision", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("outcome_detail", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id"),
    )
    op.create_index("ix_mel_tool_invocations_created_at", "mel_tool_invocations", ["created_at"])
    op.create_index("ix_mel_tool_invocations_session_id", "mel_tool_invocations", ["session_id"])
    op.create_index("ix_mel_tool_invocations_connection_id", "mel_tool_invocations", ["connection_id"])
    op.create_index("ix_mel_tool_invocations_proposal_id", "mel_tool_invocations", ["proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_mel_tool_invocations_proposal_id", table_name="mel_tool_invocations")
    op.drop_index("ix_mel_tool_invocations_connection_id", table_name="mel_tool_invocations")
    op.drop_index("ix_mel_tool_invocations_session_id", table_name="mel_tool_invocations")
    op.drop_index("ix_mel_tool_invocations_created_at", table_name="mel_tool_invocations")
    op.drop_table("mel_tool_invocations")
