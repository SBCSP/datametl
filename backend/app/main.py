from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import auth as auth_lib
from app.api import (
    activity,
    auth,
    billing,
    chat,
    comparisons,
    connections,
    jobs,
    mappings,
    mcp,
    metrics,
    migrations,
    pipelines,
    prometheus,
    schedules,
    snapshots,
    sql_scripts,
    taps,
    verifications,
)
from app.api import (
    settings as settings_api,
)
from app.config import settings
from app.mcp.server import create_http_app as create_external_mcp_app

logging.basicConfig(level=settings.log_level)

_docs = "/docs" if settings.docs_enabled else None
_redoc = "/redoc" if settings.docs_enabled else None
_openapi = "/openapi.json" if settings.docs_enabled else None

# Pro-gated FastMCP (streamable HTTP). Lifespan must be wired into FastAPI.
_external_mcp_app = create_external_mcp_app()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with _external_mcp_app.lifespan(_external_mcp_app):
        yield


app = FastAPI(
    title="DataMETL",
    description="Local-first data migration tool — schema introspection, comparison, and mapping API",
    version="0.1.0",
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
    lifespan=_lifespan,
)

# Endpoints reachable without a bearer token (only consulted when AUTH_ENABLED).
_AUTH_OPEN_EXACT = {"/health", "/api/auth/login", "/api/auth/status", "/api/billing/stripe/webhook"} | ({"/openapi.json"} if settings.docs_enabled else set())


class AuthMiddleware(BaseHTTPMiddleware):
    """Require a valid bearer token for /api/* (and /mcp/*) when AUTH_ENABLED. No-op when disabled.

    Added *before* CORS so CORS stays the outermost middleware — 401s still get CORS headers,
    and preflight OPTIONS is handled by CORS before reaching here."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.auth_enabled:
            return await call_next(request)
        path = request.url.path
        if request.method == "OPTIONS" or path in _AUTH_OPEN_EXACT or (settings.docs_enabled and path.startswith("/docs")):
            return await call_next(request)
        # /api/* and external FastMCP mount share the same optional in-app auth gate.
        if path.startswith("/api/") or path.startswith("/mcp/"):
            header = request.headers.get("authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            if auth_lib.verify_token(token) is None:
                return JSONResponse({"detail": "Not authenticated."}, status_code=401)
        return await call_next(request)


# NOTE: add auth first, CORS last → CORS is outermost (wraps auth's 401s with headers).
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(snapshots.router)
app.include_router(comparisons.router)
app.include_router(mappings.router)
app.include_router(migrations.router)
app.include_router(verifications.router)
app.include_router(sql_scripts.router)
app.include_router(schedules.router)
app.include_router(pipelines.router)
app.include_router(taps.router)
app.include_router(chat.router)
app.include_router(mcp.router)
app.include_router(activity.router)
app.include_router(metrics.router)
app.include_router(prometheus.router)
app.include_router(settings_api.router)
app.include_router(billing.router)
app.include_router(jobs.router)

# External FastMCP — Pro middleware lives on the sub-app; Community → 402.
app.mount("/mcp/external", _external_mcp_app)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
