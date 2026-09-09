"""Public control-plane tables for schema-per-tenant

Revision ID: 0019_public_control_plane
Revises: 0018_chat_session_tool_cards
Create Date: 2026-09-09 01:00:00

Creates tenants / users / oauth_identities / tenant_memberships / tenant_licenses
in the ``public`` schema. Existing app tables remain in public until cutover
(``python -m app.scripts.cutover_tenant_schema``). Tenant schemas use
``tenant_<uuidhex>`` naming and are provisioned by ``app.tenancy.provision``.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_public_control_plane"
down_revision: str | None = "0018_chat_session_tool_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("schema_name", name="uq_tenants_schema_name"),
        schema="public",
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema="public",
    )

    op.create_table(
        "oauth_identities",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("profile", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        schema="public",
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("public.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("public.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership"),
        schema="public",
    )

    op.create_table(
        "tenant_licenses",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("public.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(32), nullable=False, server_default="community"),
        sa.Column("license_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_licenses_tenant_id"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("tenant_licenses", schema="public")
    op.drop_table("tenant_memberships", schema="public")
    op.drop_table("oauth_identities", schema="public")
    op.drop_table("users", schema="public")
    op.drop_table("tenants", schema="public")
