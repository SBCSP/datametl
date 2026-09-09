"""Request/job tenant context via contextvars (middleware + get_db + enqueue)."""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tenancy.middleware import TenantContext

_tenant_ctx: ContextVar[TenantContext | None] = ContextVar("datametl_tenant_context", default=None)


def get_tenant_context() -> TenantContext | None:
    return _tenant_ctx.get()


def set_tenant_context(ctx: TenantContext | None) -> Token[TenantContext | None]:
    return _tenant_ctx.set(ctx)


def reset_tenant_context(token: Token[TenantContext | None]) -> None:
    _tenant_ctx.reset(token)
