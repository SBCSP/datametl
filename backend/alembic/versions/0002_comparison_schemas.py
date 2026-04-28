"""schema-scoped comparisons

Revision ID: 0002_comparison_schemas
Revises: 0001_initial
Create Date: 2026-04-27 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_comparison_schemas"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("comparisons", sa.Column("source_schema", sa.String(255), nullable=True))
    op.add_column("comparisons", sa.Column("dest_schema", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("comparisons", "dest_schema")
    op.drop_column("comparisons", "source_schema")
