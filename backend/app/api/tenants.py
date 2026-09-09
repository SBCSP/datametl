"""Tenant onboarding API (TENANT-ONBOARD-v1).

Authenticated users with zero ``TenantMembership`` rows must create a workspace
via ``POST /api/tenants`` before using the app. Cutover bind alone does **not**
count as onboarded.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import auth as auth_lib
from app.db import get_db
from app.models.tenant_control import Tenant, TenantMembership, User
from app.tenancy.binding import resolve_user_for_subject
from app.tenancy.provision import create_tenant_schema, normalize_tenant_kind
from app.tenancy.slug import is_valid_slug

router = APIRouter(prefix="/api/tenants", tags=["tenants"])

ApiKind = Literal["personal", "organization"]


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _kind_for_api(db_kind: str) -> ApiKind:
    if db_kind == "org":
        return "organization"
    return "personal"


def _require_user(
    db: Session,
    authorization: str | None,
) -> tuple[str, User]:
    subject = auth_lib.verify_token(_bearer(authorization) or "")
    if subject is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    user = resolve_user_for_subject(db, subject)
    if user is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No local user for this session; complete GitHub OAuth or legacy login.",
        )
    return subject, user


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64)
    kind: ApiKind

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if not is_valid_slug(s):
            raise ValueError(
                "slug must be lowercase [a-z0-9-] with no leading/trailing hyphen"
            )
        return s

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        n = (v or "").strip()
        if not n:
            raise ValueError("name is required")
        return n


class TenantSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: ApiKind
    role: str | None = None
    schema_name: str
    created_at: datetime | None = None


class TenantsMeResponse(BaseModel):
    needs_onboarding: bool
    tenants: list[TenantSummary]


@router.get("/me", response_model=TenantsMeResponse)
def tenants_me(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> TenantsMeResponse:
    """Return memberships and whether the user still needs first-workspace onboard."""
    _, user = _require_user(db, authorization)
    rows = list(
        db.execute(
            select(TenantMembership, Tenant)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(TenantMembership.user_id == user.id)
            .order_by(TenantMembership.created_at, TenantMembership.id)
        ).all()
    )
    tenants = [
        TenantSummary(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            kind=_kind_for_api(tenant.kind),
            role=mem.role,
            schema_name=tenant.schema_name,
            created_at=tenant.created_at,
        )
        for mem, tenant in rows
    ]
    return TenantsMeResponse(needs_onboarding=len(tenants) == 0, tenants=tenants)


@router.post("", response_model=TenantSummary, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> TenantSummary:
    """Create the caller's first workspace (v1: reject if any membership exists)."""
    _, user = _require_user(db, authorization)
    existing = db.execute(
        select(TenantMembership.id).where(TenantMembership.user_id == user.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Already a member of a workspace; v1 supports one workspace per user.",
        )

    # Ensure slug uniqueness message is friendly (provision also checks).
    taken = db.execute(
        select(Tenant.id).where(Tenant.slug == payload.slug).limit(1)
    ).scalar_one_or_none()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Slug already taken: {payload.slug}")

    try:
        db_kind = normalize_tenant_kind(payload.kind)
        tenant = create_tenant_schema(
            db,
            kind=db_kind,
            name=payload.name,
            slug=payload.slug,
            owner_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Could not create workspace (slug or schema conflict).",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Workspace provisioning failed: {exc.__class__.__name__}",
        ) from exc

    return TenantSummary(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        kind=_kind_for_api(tenant.kind),
        role="owner",
        schema_name=tenant.schema_name,
        created_at=tenant.created_at,
    )

