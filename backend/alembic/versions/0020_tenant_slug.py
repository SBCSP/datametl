"""Add unique Tenant.slug for onboarding

Revision ID: 0020_tenant_slug
Revises: 0019_public_control_plane
Create Date: 2026-09-09 14:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_tenant_slug"
down_revision: str | None = "0019_public_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("slug", sa.String(64), nullable=True),
        schema="public",
    )
    # Backfill existing rows (e.g. cutover default) with a stable unique slug.
    op.execute(
        sa.text(
            "UPDATE public.tenants SET slug = "
            "'t-' || replace(id::text, '-', '') "
            "WHERE slug IS NULL OR slug = ''"
        )
    )
    op.alter_column("tenants", "slug", nullable=False, schema="public")
    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"], schema="public")


def downgrade() -> None:
    op.drop_constraint("uq_tenants_slug", "tenants", schema="public", type_="unique")
    op.drop_column("tenants", "slug", schema="public")
