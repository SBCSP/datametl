"""Tap — API data sources + fetch runs

Revision ID: 0015_taps
Revises: 0014_introspection_runs
Create Date: 2026-06-05 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_taps"
down_revision: Union[str, None] = "0014_introspection_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False, server_default="GET"),
        sa.Column("records_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("dest_connection_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dest_table", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("write_mode", sa.String(length=16), nullable=False, server_default="append"),
        sa.Column("encrypted_config", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tap_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tap_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("taps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("sample", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tap_runs_tap", "tap_runs", ["tap_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_tap_runs_tap", table_name="tap_runs")
    op.drop_table("tap_runs")
    op.drop_table("taps")
