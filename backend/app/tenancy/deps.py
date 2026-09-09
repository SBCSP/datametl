"""FastAPI dependencies for TENANT-ENFORCE."""
from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.tenancy.context import get_tenant_context
from app.tenancy.middleware import TenantContext
from app.tenancy.search_path import set_search_path


def get_request_tenant(request: Request) -> TenantContext | None:
    return getattr(request.state, "tenant_context", None) or get_tenant_context()


def require_tenant_context(request: Request) -> TenantContext | None:
    """Fail closed for Mel routes when ``TENANT_ENFORCE_ENABLED`` and no tenant is bound.

    When enforce is off, returns the context if present, else ``None`` (legacy Mel behavior).
    """
    ctx = get_request_tenant(request)
    if not settings.tenant_enforce_enabled:
        return ctx
    if ctx is None:
        raise HTTPException(
            status_code=403,
            detail="Tenant context required; no cross-tenant Mel.",
        )
    return ctx


def get_tenant_db(request: Request) -> Generator[Session, None, None]:
    """Session with ``search_path`` set when tenant_context is present on the request."""
    db = SessionLocal()
    try:
        ctx = get_request_tenant(request)
        if ctx is not None:
            set_search_path(db.connection(), ctx.schema_name)
        yield db
    finally:
        db.close()
