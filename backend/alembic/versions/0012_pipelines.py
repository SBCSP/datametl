"""ETL pipelines: pipelines + steps + runs + run steps

Revision ID: 0012_pipelines
Revises: 0011_script_description
Create Date: 2026-06-04 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_pipelines"
down_revision: Union[str, None] = "0011_script_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "pipeline_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipelines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("step_type", sa.String(length=16), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pipeline_steps_pipeline", "pipeline_steps", ["pipeline_id", "step_order"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipelines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pipeline_runs_pipeline", "pipeline_runs", ["pipeline_id", "created_at"])

    op.create_table(
        "pipeline_run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("step_type", sa.String(length=16), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_run_steps_run", "pipeline_run_steps", ["run_id", "step_order"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_run_steps_run", table_name="pipeline_run_steps")
    op.drop_table("pipeline_run_steps")
    op.drop_index("ix_pipeline_runs_pipeline", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index("ix_pipeline_steps_pipeline", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")
    op.drop_table("pipelines")
