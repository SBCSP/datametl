"""Public-schema control-plane models for schema-per-tenant (team-on-install).

Tenant *data* (connections, Mel, migrations, …) lives in per-tenant Postgres schemas
named ``tenant_<uuidhex>``. These tables stay in ``public`` and never hold Mel rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

# Explicit public schema so control tables never land in a tenant search_path by accident.
_PUBLIC = {"schema": "public"}


class Tenant(Base):
    """One install-local tenant. ``schema_name`` is always ``tenant_<uuidhex>``."""

    __tablename__ = "tenants"
    __table_args__ = _PUBLIC

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # personal | org
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Canonical: tenant_ + uuid.hex (32 lowercase hex chars, no dashes).
    schema_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    """Install-local user (GitHub OAuth subject linked via OAuthIdentity)."""

    __tablename__ = "users"
    __table_args__ = _PUBLIC

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional scrypt hash for AUTH_LEGACY_BASIC escape hatch (one-release).
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OAuthIdentity(Base):
    """External IdP link. v1 provider is GitHub; callback wiring is a follow-up milestone."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        _PUBLIC,
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "github"
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # Non-secret profile stub (login, avatar url, …) — never store tokens here.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantMembership(Base):
    """User ↔ tenant membership. No cross-tenant Mel; membership gates schema binding."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership"),
        _PUBLIC,
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False
    )
    # owner | admin | member
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantLicense(Base):
    """Pro license scoped to a tenant (stub columns; entitlements wiring is follow-up)."""

    __tablename__ = "tenant_licenses"
    __table_args__ = _PUBLIC

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # community | pro (mirrors license.entitlements tiers)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="community")
    # Compact dmtl1… token or null when community / unset.
    license_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
