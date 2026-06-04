"""scheduled SQL scripts (cron) + per-run history

Revision ID: 0010_scheduled_scripts
Revises: 0009_script_run_counts
Create Date: 2026-06-03 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_scheduled_scripts"
down_revision: Union[str, None] = "0009_script_run_counts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_scripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "script_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sql_scripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connection_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cron", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("allow_writes", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # The dispatcher scans for enabled schedules that are due — index that hot path.
    op.create_index(
        "ix_scheduled_scripts_due",
        "scheduled_scripts",
        ["enabled", "next_run_at"],
    )

    op.create_table(
        "scheduled_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_scripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_runs_schedule",
        "scheduled_runs",
        ["schedule_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_runs_schedule", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
    op.drop_index("ix_scheduled_scripts_due", table_name="scheduled_scripts")
    op.drop_table("scheduled_scripts")
