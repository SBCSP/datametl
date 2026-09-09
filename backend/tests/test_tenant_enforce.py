"""TENANT-ENFORCE: middleware binding, membership header, Mel fail-closed, search_path."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.config import settings
from app.models.tenant_control import Tenant, TenantMembership, User
from app.tenancy.binding import TenantBindError, resolve_active_tenant
from app.tenancy.cutover import DEFAULT_CUTOVER_TENANT_ID
from app.tenancy.deps import require_tenant_context
from app.tenancy.middleware import TenantBindingMiddleware, TenantContext
from app.tenancy.names import tenant_schema_name
from app.tenancy.search_path import set_search_path


def _tenant(tid: uuid.UUID | None = None, name: str = "T") -> MagicMock:
    tid = tid or uuid.uuid4()
    t = MagicMock()
    t.id = tid
    t.schema_name = tenant_schema_name(tid)
    t.name = name
    return t


def _membership(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str = "owner",
    created_at: datetime | None = None,
) -> MagicMock:
    m = MagicMock()
    m.user_id = user_id
    m.tenant_id = tenant_id
    m.role = role
    m.id = uuid.uuid4()
    m.created_at = created_at or datetime(2026, 1, 1, tzinfo=UTC)
    return m


def _user(email: str = "a@example.com") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = email
    u.display_name = None
    return u


def _db_for_resolve(
    *,
    user: MagicMock | None = None,
    memberships: list | None = None,
    tenants: list | None = None,
) -> MagicMock:
    memberships = list(memberships or [])
    tenants_by_id = {t.id: t for t in (tenants or [])}
    db = MagicMock()

    def get(model: object, key: object) -> object:
        if model is Tenant or getattr(model, "__name__", "") == "Tenant":
            return tenants_by_id.get(key)  # type: ignore[arg-type]
        if model is User or getattr(model, "__name__", "") == "User":
            return user if user is not None and user.id == key else None
        return tenants_by_id.get(key)  # type: ignore[arg-type]

    db.get.side_effect = get

    def execute(stmt: object) -> MagicMock:
        result = MagicMock()
        # Membership queries
        try:
            tables = {t.name for t in stmt.get_final_froms()}  # type: ignore[attr-defined]
        except Exception:
            tables = set()
        s = str(stmt).lower()
        if "tenant_memberships" in tables or "tenant_memberships" in s:
            result.scalars.return_value = memberships
            result.scalar_one_or_none.return_value = memberships[0] if memberships else None
            return result
        if "users" in tables or ("users" in s and "tenant_memberships" not in s):
            result.scalar_one_or_none.return_value = user
            result.scalars.return_value = [user] if user else []
            return result
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value = []
        return result

    db.execute.side_effect = execute
    return db


def test_resolve_sole_membership() -> None:
    user = _user()
    tenant = _tenant()
    db = _db_for_resolve(
        user=user,
        memberships=[_membership(user.id, tenant.id)],
        tenants=[tenant],
    )
    with patch("app.tenancy.binding.resolve_user_for_subject", return_value=user):
        got = resolve_active_tenant(db, subject=user.email, header_tenant_id=None)
    assert got is not None
    assert got.tenant_id == tenant.id
    assert got.schema_name == tenant.schema_name
    assert got.role == "owner"


def test_resolve_header_membership() -> None:
    user = _user()
    t1, t2 = _tenant(), _tenant()
    mems = [
        _membership(user.id, t1.id, created_at=datetime(2026, 1, 1, tzinfo=UTC)),
        _membership(user.id, t2.id, role="member", created_at=datetime(2026, 2, 1, tzinfo=UTC)),
    ]
    db = _db_for_resolve(user=user, memberships=mems, tenants=[t1, t2])
    with patch("app.tenancy.binding.resolve_user_for_subject", return_value=user):
        got = resolve_active_tenant(db, subject=user.email, header_tenant_id=str(t2.id))
    assert got is not None
    assert got.tenant_id == t2.id
    assert got.role == "member"


def test_resolve_header_rejects_non_member() -> None:
    user = _user()
    t1, t2 = _tenant(), _tenant()
    db = _db_for_resolve(
        user=user,
        memberships=[_membership(user.id, t1.id)],
        tenants=[t1, t2],
    )
    with patch("app.tenancy.binding.resolve_user_for_subject", return_value=user):
        with pytest.raises(TenantBindError, match="Not a member"):
            resolve_active_tenant(db, subject=user.email, header_tenant_id=str(t2.id))


def test_resolve_cutover_legacy_fallback() -> None:
    cut = _tenant(DEFAULT_CUTOVER_TENANT_ID, name="Default")
    db = _db_for_resolve(user=None, memberships=[], tenants=[cut])
    with patch("app.tenancy.binding.resolve_user_for_subject", return_value=None):
        got = resolve_active_tenant(
            db,
            subject="admin",
            header_tenant_id=None,
            auth_enabled=True,
            auth_legacy_basic=True,
        )
    assert got is not None
    assert got.tenant_id == DEFAULT_CUTOVER_TENANT_ID
    assert got.schema_name == tenant_schema_name(DEFAULT_CUTOVER_TENANT_ID)


def test_middleware_sets_tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "auth_legacy_basic", True)

    tid = DEFAULT_CUTOVER_TENANT_ID
    schema = tenant_schema_name(tid)
    ctx = TenantContext(tenant_id=tid, schema_name=schema)

    app = FastAPI()

    @app.get("/api/ping")
    async def ping(request: Request) -> dict[str, str | None]:
        tc = getattr(request.state, "tenant_context", None)
        return {
            "tenant_id": str(tc.tenant_id) if tc else None,
            "schema": tc.schema_name if tc else None,
        }

    app.add_middleware(TenantBindingMiddleware)

    with (
        patch("app.tenancy.middleware.bind_tenant_for_request", return_value=ctx),
        patch("app.tenancy.middleware.SessionLocal") as sl,
    ):
        sl.return_value.__enter__ = lambda s: MagicMock()
        sl.return_value.__exit__ = lambda *a: None
        client = TestClient(app)
        r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["tenant_id"] == str(tid)
    assert r.json()["schema"] == schema


def test_middleware_skips_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(TenantBindingMiddleware)
    with patch("app.tenancy.middleware.SessionLocal") as sl:
        client = TestClient(app)
        r = client.get("/health")
    assert r.status_code == 200
    sl.assert_not_called()


def test_require_tenant_mel_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    app = FastAPI()

    @app.post("/api/chat/stream")
    def stream(
        _tenant: TenantContext | None = Depends(require_tenant_context),
    ) -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(TenantBindingMiddleware)

    with (
        patch("app.tenancy.middleware.bind_tenant_for_request", return_value=None),
        patch("app.tenancy.middleware.SessionLocal") as sl,
    ):
        sl.return_value.__enter__ = lambda s: MagicMock()
        sl.return_value.__exit__ = lambda *a: None
        client = TestClient(app)
        r = client.post("/api/chat/stream")
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "Tenant context" in detail or "cross-tenant" in detail.lower()


def test_get_db_sets_search_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tenancy.context import reset_tenant_context, set_tenant_context

    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    tid = uuid.uuid4()
    schema = tenant_schema_name(tid)
    token = set_tenant_context(TenantContext(tenant_id=tid, schema_name=schema))
    try:
        mock_session = MagicMock()
        mock_conn = MagicMock()
        mock_session.connection.return_value = mock_conn
        with (
            patch("app.db.SessionLocal", return_value=mock_session),
            patch("app.tenancy.search_path.set_search_path") as sp,
        ):
            from app.db import get_db

            gen = get_db()
            db = next(gen)
            assert db is mock_session
            sp.assert_called_once_with(mock_conn, schema)
            with pytest.raises(StopIteration):
                next(gen)
    finally:
        reset_tenant_context(token)


def test_job_bind_defaults_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tenancy.job_bind import resolve_job_schema

    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    cut = _tenant(DEFAULT_CUTOVER_TENANT_ID)
    db = MagicMock()
    db.get.return_value = cut
    tid, schema = resolve_job_schema(db, None)
    assert tid == DEFAULT_CUTOVER_TENANT_ID
    assert schema == cut.schema_name


def test_job_bind_uses_payload_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tenancy.job_bind import resolve_job_schema

    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    t = _tenant()
    db = MagicMock()
    db.get.return_value = t
    tid, schema = resolve_job_schema(db, str(t.id))
    assert tid == t.id
    assert schema == t.schema_name


def test_set_search_path_still_safe() -> None:
    conn = MagicMock()
    schema = tenant_schema_name(uuid.uuid4())
    set_search_path(conn, schema)
    sql = str(conn.execute.call_args[0][0])
    assert f"SET search_path TO {schema}, public" in sql


def test_tenant_header_constant() -> None:
    from app.tenancy.binding import TENANT_HEADER

    assert TENANT_HEADER == "X-Tenant-Id"
