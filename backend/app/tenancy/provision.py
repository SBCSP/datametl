"""Provision a new tenant: control row + Postgres schema + tenant template DDL."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_control import Tenant, TenantLicense, TenantMembership, User
from app.tenancy.migrate import upgrade_tenant_schema
from app.tenancy.names import tenant_schema_name

log = logging.getLogger("datametl.tenancy.provision")

TenantKind = Literal["personal", "org"]


def create_tenant_schema(
    db: Session,
    *,
    kind: TenantKind,
    name: str,
    tenant_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    license_tier: str = "community",
) -> Tenant:
    """Create control-plane tenant row, membership, license stub, and physical schema.

    ``kind`` is ``personal`` or ``org``. Schema name is always ``tenant_<uuidhex>``.
    """
    if kind not in ("personal", "org"):
        raise ValueError("kind must be 'personal' or 'org'")
    tid = tenant_id or uuid.uuid4()
    schema_name = tenant_schema_name(tid)

    existing = db.execute(select(Tenant).where(Tenant.schema_name == schema_name)).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"tenant schema already registered: {schema_name}")

    tenant = Tenant(id=tid, kind=kind, name=name, schema_name=schema_name)
    db.add(tenant)
    db.flush()

    if owner_user_id is not None:
        db.add(
            TenantMembership(
                tenant_id=tid,
                user_id=owner_user_id,
                role="owner",
            )
        )

    db.add(TenantLicense(tenant_id=tid, tier=license_tier, license_token=None))
    db.flush()

    # DDL against the same DB as the session.
    conn = db.connection()
    upgrade_tenant_schema(conn, schema_name)
    db.commit()
    db.refresh(tenant)
    log.info("provisioned tenant %s kind=%s schema=%s", tid, kind, schema_name)
    return tenant


def provision_tenant(
    db: Session,
    *,
    kind: TenantKind,
    name: str,
    owner_email: str | None = None,
    owner_display_name: str | None = None,
    **kwargs: Any,
) -> tuple[Tenant, User | None]:
    """Convenience: optional owner User + ``create_tenant_schema``."""
    owner: User | None = None
    if owner_email:
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one_or_none()
        if owner is None:
            owner = User(email=owner_email, display_name=owner_display_name)
            db.add(owner)
            db.flush()
    tenant = create_tenant_schema(
        db,
        kind=kind,
        name=name,
        owner_user_id=owner.id if owner else None,
        **kwargs,
    )
    return tenant, owner
