"""Request tenant binding stub (full enforcement is TENANT-ENFORCE milestone).

Today this only documents the intended hook: resolve tenant from the authenticated
principal / header, then ``set_search_path`` on the request DB connection.
No route rewriting in this PR.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


@dataclass
class TenantContext:
    tenant_id: UUID
    schema_name: str
    role: str | None = None


# Request.state key used by future TENANT-ENFORCE middleware / deps.
TENANT_STATE_KEY = "tenant_context"


class TenantBindingMiddleware(BaseHTTPMiddleware):
    """No-op stub: does not bind search_path yet.

    TENANT-ENFORCE will:
      1. Resolve membership for the current user
      2. Reject cross-tenant Mel access
      3. Call set_search_path on the session connection
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Intentionally unset — routes keep legacy public search_path until enforce ships.
        request.state.tenant_context = None
        return await call_next(request)
