"""Request tenant binding (TENANT-ENFORCE): search_path + request.state.tenant_context."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.db import SessionLocal
from app.tenancy.binding import TENANT_HEADER, TenantBindError, resolve_active_tenant
from app.tenancy.context import reset_tenant_context, set_tenant_context

log = logging.getLogger("datametl.tenancy.middleware")


@dataclass
class TenantContext:
    tenant_id: UUID
    schema_name: str
    role: str | None = None
    user_id: UUID | None = None


# Request.state key used by deps / Mel fail-closed checks.
TENANT_STATE_KEY = "tenant_context"

# Paths that never bind a tenant (public / auth bootstrap / scrapers).
_SKIP_EXACT = {
    "/health",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/github/start",
    "/api/auth/github/callback",
    "/api/billing/stripe/webhook",
    "/metrics",
}


def _should_skip(request: Request) -> bool:
    path = request.url.path
    if request.method == "OPTIONS":
        return True
    if path in _SKIP_EXACT:
        return True
    # Onboard routes need auth but must work with zero memberships (no tenant bind).
    if path == "/api/tenants" or path.startswith("/api/tenants/"):
        return True
    if path == "/openapi.json":
        return True
    return path.startswith("/docs") or path.startswith("/redoc")


def _bearer_subject(request: Request) -> str | None:
    from app import auth as auth_lib

    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        return None
    return auth_lib.verify_token(token)


def bind_tenant_for_request(request: Request, db: Session) -> TenantContext | None:
    """Resolve and return TenantContext (or None). Raises TenantBindError on hard failures."""
    if not settings.tenant_enforce_enabled:
        return None
    subject = _bearer_subject(request)
    header_tid = request.headers.get(TENANT_HEADER) or request.headers.get(TENANT_HEADER.lower())
    resolved = resolve_active_tenant(
        db,
        subject=subject,
        header_tenant_id=header_tid,
    )
    if resolved is None:
        return None
    return TenantContext(
        tenant_id=resolved.tenant_id,
        schema_name=resolved.schema_name,
        role=resolved.role,
        user_id=resolved.user_id,
    )


class TenantBindingMiddleware(BaseHTTPMiddleware):
    """Bind every authenticated request to a tenant schema via ``request.state`` + contextvar.

    Must sit *inside* AuthMiddleware (added before Auth in FastAPI) so unauthenticated
    /api requests are already rejected. Sets ``search_path`` later in ``get_db``.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.tenant_context = None
        token = set_tenant_context(None)
        try:
            if not settings.tenant_enforce_enabled or _should_skip(request):
                return await call_next(request)

            try:
                with SessionLocal() as db:
                    ctx = bind_tenant_for_request(request, db)
            except TenantBindError as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            except Exception:
                log.exception("tenant binding failed")
                return JSONResponse(
                    {"detail": "Tenant binding failed."},
                    status_code=500,
                )

            request.state.tenant_context = ctx
            token = set_tenant_context(ctx)
            return await call_next(request)
        finally:
            reset_tenant_context(token)
