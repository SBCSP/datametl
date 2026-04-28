"""migration runs + per-table progress + mapping skip flag

Revision ID: 0003_migration_runs
Revises: 0002_comparison_schemas
Create Date: 2026-04-27 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_migration_runs"
down_revision: Union[str, None] = "0002_comparison_schemas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `create_type=False` prevents SQLAlchemy's automatic CREATE TYPE when these enums appear
# inside create_table — we create them ourselves below with checkfirst=True so the
# migration is idempotent across partially-applied attempts.
run_status = postgresql.ENUM(
    "pending", "running", "succeeded", "failed", "cancelled",
    name="migration_run_status",
    create_type=False,
)
table_status = postgresql.ENUM(
    "pending", "running", "succeeded", "failed", "skipped",
    name="migration_table_status",
    create_type=False,
)
conflict_mode = postgresql.ENUM(
    "truncate", "append", "abort",
    name="migration_conflict_mode",
    create_type=False,
)


def upgrade() -> None:
    # Existing-table tweak: per-column skip flag for migration.
    op.add_column(
        "mappings",
        sa.Column("skip", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)
    table_status.create(bind, checkfirst=True)
    conflict_mode.create(bind, checkfirst=True)

    op.create_table(
        "migration_runs",
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
        "migration_run_tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("migration_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_table", sa.String(255), nullable=False),
        sa.Column("dest_table", sa.String(255), nullable=False),
        sa.Column("conflict_mode", conflict_mode, nullable=False, server_default="truncate"),
        sa.Column("status", table_status, nullable=False, server_default="pending"),
        sa.Column("rows_read", sa.BigInteger, nullable=True),
        sa.Column("rows_written", sa.BigInteger, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("verification", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "source_table", "dest_table", name="uq_run_table"),
    )


def downgrade() -> None:
    op.drop_table("migration_run_tables")
    op.drop_table("migration_runs")
    bind = op.get_bind()
    conflict_mode.drop(bind, checkfirst=True)
    table_status.drop(bind, checkfirst=True)
    run_status.drop(bind, checkfirst=True)
    op.drop_column("mappings", "skip")
