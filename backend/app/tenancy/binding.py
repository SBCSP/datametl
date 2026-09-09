"""Resolve active tenant for a principal (shared by middleware + tests)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant_control import Tenant, TenantMembership, User
from app.tenancy.cutover import DEFAULT_CUTOVER_TENANT_ID
from app.tenancy.names import tenant_schema_name

log = logging.getLogger("datametl.tenancy.binding")

TENANT_HEADER = "X-Tenant-Id"


@dataclass(frozen=True)
class ResolvedTenant:
    tenant_id: uuid.UUID
    schema_name: str
    role: str | None
    user_id: uuid.UUID | None = None


class TenantBindError(Exception):
    """Raised when enforce is on and no safe tenant can be bound."""

    def __init__(self, detail: str, *, status_code: int = 403) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def resolve_user_for_subject(db: Session, subject: str) -> User | None:
    """Map bearer ``sub`` (legacy username or OAuth session username) to ``public.users``."""
    sub = (subject or "").strip()
    if not sub:
        return None
    by_email = db.execute(select(User).where(User.email == sub)).scalar_one_or_none()
    if by_email is not None:
        return by_email
    by_name = db.execute(select(User).where(User.display_name == sub)).scalar_one_or_none()
    if by_name is not None:
        return by_name
    if sub.startswith("github:"):
        rest = sub[len("github:") :]
        try:
            uid = uuid.UUID(rest)
            return db.get(User, uid)
        except ValueError:
            # github:<login> — match oauth profile login is out of band; try display_name
            return db.execute(select(User).where(User.display_name == rest)).scalar_one_or_none()
    return None


def _memberships_for_user(db: Session, user_id: uuid.UUID) -> list[TenantMembership]:
    return list(
        db.execute(
            select(TenantMembership).where(TenantMembership.user_id == user_id)
        ).scalars()
    )


def cutover_tenant_if_exists(db: Session) -> ResolvedTenant | None:
    tenant = db.get(Tenant, DEFAULT_CUTOVER_TENANT_ID)
    if tenant is None:
        return None
    return ResolvedTenant(
        tenant_id=tenant.id,
        schema_name=tenant.schema_name or tenant_schema_name(tenant.id),
        role=None,
        user_id=None,
    )


def resolve_active_tenant(
    db: Session,
    *,
    subject: str | None,
    header_tenant_id: str | None,
    auth_enabled: bool | None = None,
    auth_legacy_basic: bool | None = None,
) -> ResolvedTenant | None:
    """Pick the active tenant for this request.

    Rules (locked product):
      1. If ``X-Tenant-Id`` is set and the user is a member → that tenant
      2. Else sole membership, or first membership (deterministic by created_at/id)
      3. Else if AUTH_LEGACY_BASIC (or auth disabled) and cutover tenant exists → cutover
      4. Else None (caller fail-closes Mel / optionally 403)
    """
    auth_on = settings.auth_enabled if auth_enabled is None else auth_enabled
    legacy = settings.auth_legacy_basic if auth_legacy_basic is None else auth_legacy_basic

    user: User | None = None
    memberships: list[TenantMembership] = []
    if subject:
        user = resolve_user_for_subject(db, subject)
        if user is not None:
            memberships = _memberships_for_user(db, user.id)

    # Header wins only when membership proves it (no cross-tenant Mel / data).
    if header_tenant_id:
        try:
            wanted = uuid.UUID(header_tenant_id.strip())
        except ValueError as exc:
            raise TenantBindError(f"Invalid {TENANT_HEADER} header.") from exc
        if not memberships:
            raise TenantBindError("Not a member of the requested tenant.")
        match = next((m for m in memberships if m.tenant_id == wanted), None)
        if match is None:
            raise TenantBindError("Not a member of the requested tenant.")
        tenant = db.get(Tenant, match.tenant_id)
        if tenant is None:
            raise TenantBindError("Requested tenant does not exist.")
        return ResolvedTenant(
            tenant_id=tenant.id,
            schema_name=tenant.schema_name,
            role=match.role,
            user_id=user.id if user else None,
        )

    if len(memberships) == 1:
        m = memberships[0]
        tenant = db.get(Tenant, m.tenant_id)
        if tenant is not None:
            return ResolvedTenant(
                tenant_id=tenant.id,
                schema_name=tenant.schema_name,
                role=m.role,
                user_id=user.id if user else None,
            )

    if len(memberships) > 1:
        # Deterministic default: earliest membership.
        memberships_sorted = sorted(memberships, key=lambda m: (m.created_at, str(m.id)))
        m = memberships_sorted[0]
        tenant = db.get(Tenant, m.tenant_id)
        if tenant is not None:
            return ResolvedTenant(
                tenant_id=tenant.id,
                schema_name=tenant.schema_name,
                role=m.role,
                user_id=user.id if user else None,
            )

    # Legacy / unauthenticated install: bind the staging cutover tenant when present.
    if (not auth_on) or legacy:
        cut = cutover_tenant_if_exists(db)
        if cut is not None:
            if user is not None:
                cut = ResolvedTenant(
                    tenant_id=cut.tenant_id,
                    schema_name=cut.schema_name,
                    role=None,
                    user_id=user.id,
                )
            log.debug("binding cutover tenant %s (legacy/auth-off fallback)", cut.tenant_id)
            return cut

    return None
