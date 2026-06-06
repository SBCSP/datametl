"""add optional environment label to connections

Revision ID: 0013_connection_environment
Revises: 0012_pipelines
Create Date: 2026-06-04 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_connection_environment"
down_revision: Union[str, None] = "0012_pipelines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("environment", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "environment")
