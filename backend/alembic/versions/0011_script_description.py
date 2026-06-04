"""add informational description to SQL scripts

Revision ID: 0011_script_description
Revises: 0010_scheduled_scripts
Create Date: 2026-06-04 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_script_description"
down_revision: Union[str, None] = "0010_scheduled_scripts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sql_scripts",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("sql_scripts", "description")
