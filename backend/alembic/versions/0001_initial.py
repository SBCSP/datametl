"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "schema_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("normalized_schema", postgresql.JSONB, nullable=False),
        sa.Column("warnings", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    op.create_table(
        "comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schema_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dest_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schema_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("diff", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "comparison_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comparisons.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_table", sa.String(255), nullable=False),
        sa.Column("source_column", sa.String(255), nullable=False),
        sa.Column("dest_table", sa.String(255), nullable=False),
        sa.Column("dest_column", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(255), nullable=False),
        sa.Column("default_dest_type", sa.String(255), nullable=False),
        sa.Column("override_dest_type", sa.String(255), nullable=True),
        sa.Column("is_lossy", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "comparison_id", "source_table", "source_column", name="uq_mapping_per_source_col"
        ),
    )


def downgrade() -> None:
    op.drop_table("mappings")
    op.drop_table("comparisons")
    op.drop_table("schema_snapshots")
    op.drop_table("connections")
