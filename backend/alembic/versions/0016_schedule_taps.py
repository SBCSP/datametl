"""Schedules can target a Tap (not just a SQL script)

Revision ID: 0016_schedule_taps
Revises: 0015_taps
Create Date: 2026-06-05 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_schedule_taps"
down_revision: Union[str, None] = "0015_taps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_scripts",
        sa.Column("target_kind", sa.String(length=16), nullable=False, server_default="script"),
    )
    op.add_column(
        "scheduled_scripts",
        sa.Column("tap_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "scheduled_scripts",
        sa.Column("tap_write_mode", sa.String(length=16), nullable=True),
    )
    op.create_foreign_key(
        "fk_scheduled_scripts_tap",
        "scheduled_scripts",
        "taps",
        ["tap_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Tap schedules have no script — allow NULL.
    op.alter_column("scheduled_scripts", "script_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.alter_column("scheduled_scripts", "script_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_constraint("fk_scheduled_scripts_tap", "scheduled_scripts", type_="foreignkey")
    op.drop_column("scheduled_scripts", "tap_write_mode")
    op.drop_column("scheduled_scripts", "tap_id")
    op.drop_column("scheduled_scripts", "target_kind")
