"""track SQL script run count + last run time

Revision ID: 0009_script_run_counts
Revises: 0008_mcp_session
Create Date: 2026-06-03 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_script_run_counts"
down_revision: Union[str, None] = "0008_mcp_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sql_scripts",
        sa.Column("run_count", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sql_scripts",
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sql_scripts", "last_run_at")
    op.drop_column("sql_scripts", "run_count")
