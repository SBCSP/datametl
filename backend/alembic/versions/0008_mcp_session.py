"""active MCP session (one read-only live connection at a time)

Revision ID: 0008_mcp_session
Revises: 0007_chat_sessions
Create Date: 2026-06-01 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_mcp_session"
down_revision: Union[str, None] = "0007_chat_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mcp_session")
