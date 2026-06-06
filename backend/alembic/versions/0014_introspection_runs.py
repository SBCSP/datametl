"""track schema-introspection runs (so in-flight introspects show in activity / runs)

Revision ID: 0014_introspection_runs
Revises: 0013_connection_environment
Create Date: 2026-06-05 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_introspection_runs"
down_revision: Union[str, None] = "0013_connection_environment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "introspection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_count", sa.Integer(), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_introspection_runs_conn", "introspection_runs", ["connection_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_introspection_runs_conn", table_name="introspection_runs")
    op.drop_table("introspection_runs")
