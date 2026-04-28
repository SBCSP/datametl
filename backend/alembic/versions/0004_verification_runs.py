"""standalone verification runs

Revision ID: 0004_verification_runs
Revises: 0003_migration_runs
Create Date: 2026-04-27 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_verification_runs"
down_revision: Union[str, None] = "0003_migration_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# create_type=False so SQLAlchemy doesn't double-CREATE TYPE inside create_table.
# We create them ourselves (with checkfirst=True) right before the create_table call.
run_status = postgresql.ENUM(
    "pending", "running", "succeeded", "failed", "cancelled",
    name="verification_run_status",
    create_type=False,
)
table_status = postgresql.ENUM(
    "pending", "running", "passed", "failed", "skipped",
    name="verification_table_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)
    table_status.create(bind, checkfirst=True)

    op.create_table(
        "verification_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "comparison_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comparisons.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", run_status, nullable=False, server_default="pending"),
        sa.Column("plan", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "verification_run_tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("verification_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_table", sa.String(255), nullable=False),
        sa.Column("dest_table", sa.String(255), nullable=False),
        sa.Column("level", sa.String(64), nullable=False, server_default="count_and_sample"),
        sa.Column("status", table_status, nullable=False, server_default="pending"),
        sa.Column("results", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "source_table", "dest_table", name="uq_verif_run_table"),
    )


def downgrade() -> None:
    op.drop_table("verification_run_tables")
    op.drop_table("verification_runs")
    bind = op.get_bind()
    table_status.drop(bind, checkfirst=True)
    run_status.drop(bind, checkfirst=True)
