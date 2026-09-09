"""TENANT-ONBOARD-v1: slug helpers, me/create API, middleware skip, kind mapping."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.config import settings
from app.models.tenant_control import Tenant, TenantMembership, User
from app.tenancy.middleware import TenantBindingMiddleware
from app.tenancy.provision import normalize_tenant_kind
from app.tenancy.slug import is_valid_slug, slugify_name


def test_slugify_name_basic() -> None:
    assert slugify_name("Acme Corp") == "acme-corp"
    assert slugify_name("  Hello___World!! ") == "hello-world"
    assert slugify_name("") == "workspace"
    assert slugify_name("---") == "workspace"
    assert is_valid_slug("acme-corp")
    assert is_valid_slug("a1")
    assert not is_valid_slug("-acme")
    assert not is_valid_slug("acme-")
    assert not is_valid_slug("Acme")
    assert not is_valid_slug("acme_corp")
    assert not is_valid_slug("")


def test_normalize_kind_organization_to_org() -> None:
    assert normalize_tenant_kind("organization") == "org"
    assert normalize_tenant_kind("personal") == "personal"
    assert normalize_tenant_kind("org") == "org"
    with pytest.raises(ValueError):
        normalize_tenant_kind("migrate")
    with pytest.raises(ValueError):
        normalize_tenant_kind("both")


def test_tenant_model_has_slug_column() -> None:
    assert "slug" in Tenant.__table__.c
    assert Tenant.__table__.c.slug.unique


def test_middleware_skips_tenants_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    app = FastAPI()

    @app.get("/api/tenants/me")
    def me() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/tenants")
    def create() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(TenantBindingMiddleware)
    with patch("app.tenancy.middleware.SessionLocal") as sl:
        client = TestClient(app)
        assert client.get("/api/tenants/me").status_code == 200
        assert client.post("/api/tenants").status_code == 200
    sl.assert_not_called()


def _user() -> MagicMock:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = "ada@example.com"
    u.display_name = "Ada"
    return u


def _tenant(*, slug: str = "ada", kind: str = "personal") -> MagicMock:
    t = MagicMock(spec=Tenant)
    t.id = uuid.uuid4()
    t.name = "Ada"
    t.slug = slug
    t.kind = kind
    t.schema_name = f"tenant_{t.id.hex}"
    t.created_at = datetime(2026, 9, 1, tzinfo=UTC)
    return t


@pytest.fixture()
def auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    monkeypatch.setattr(settings, "auth_legacy_basic", False)


def test_tenants_me_needs_onboarding_when_no_memberships(
    auth_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import get_db
    from app.main import app

    user = _user()
    db = MagicMock()

    def execute(stmt: object) -> MagicMock:
        result = MagicMock()
        result.all.return_value = []
        result.scalar_one_or_none.return_value = None
        return result

    db.execute.side_effect = execute

    monkeypatch.setattr("app.auth.verify_token", lambda t: user.email if t else None)
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda db, s: user)

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.get(
            "/api/tenants/me",
            headers={"Authorization": "Bearer fake"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    body = r.json()
    assert body["needs_onboarding"] is True
    assert body["tenants"] == []


def test_tenants_me_lists_memberships(auth_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import get_db
    from app.main import app

    user = _user()
    tenant = _tenant(kind="org")
    mem = MagicMock(spec=TenantMembership)
    mem.role = "owner"
    mem.created_at = datetime(2026, 9, 1, tzinfo=UTC)
    mem.id = uuid.uuid4()

    db = MagicMock()

    def execute(stmt: object) -> MagicMock:
        result = MagicMock()
        result.all.return_value = [(mem, tenant)]
        return result

    db.execute.side_effect = execute

    monkeypatch.setattr("app.auth.verify_token", lambda t: user.email if t else None)
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda db, s: user)

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.get("/api/tenants/me", headers={"Authorization": "Bearer fake"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    body = r.json()
    assert body["needs_onboarding"] is False
    assert len(body["tenants"]) == 1
    assert body["tenants"][0]["slug"] == "ada"
    assert body["tenants"][0]["kind"] == "organization"  # org → organization
    assert body["tenants"][0]["role"] == "owner"


def test_create_tenant_maps_organization_and_rejects_second(
    auth_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import get_db
    from app.main import app

    user = _user()
    created = _tenant(slug="acme", kind="org")
    created.name = "Acme"

    db = MagicMock()
    # First call: no membership; second call in same handler: slug check → None
    calls = {"n": 0}

    def execute(stmt: object) -> MagicMock:
        calls["n"] += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    db.execute.side_effect = execute

    monkeypatch.setattr("app.auth.verify_token", lambda t: user.email if t else None)
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda db, s: user)

    def fake_create(db: object, **kwargs: object) -> MagicMock:
        assert kwargs["kind"] == "org"  # normalized
        assert kwargs["slug"] == "acme"
        assert kwargs["name"] == "Acme"
        assert kwargs["owner_user_id"] == user.id
        return created

    monkeypatch.setattr("app.api.tenants.create_tenant_schema", fake_create)

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.post(
            "/api/tenants",
            headers={"Authorization": "Bearer fake"},
            json={"name": "Acme", "slug": "acme", "kind": "organization"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["kind"] == "organization"
        assert body["slug"] == "acme"
        assert body["role"] == "owner"

        # Second create: membership exists
        def execute2(stmt: object) -> MagicMock:
            result = MagicMock()
            result.scalar_one_or_none.return_value = uuid.uuid4()
            return result

        db.execute.side_effect = execute2
        r2 = client.post(
            "/api/tenants",
            headers={"Authorization": "Bearer fake"},
            json={"name": "Other", "slug": "other", "kind": "personal"},
        )
        assert r2.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_tenant_rejects_bad_kind(auth_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db import get_db
    from app.main import app

    user = _user()
    db = MagicMock()
    monkeypatch.setattr("app.auth.verify_token", lambda t: user.email if t else None)
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda db, s: user)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.post(
            "/api/tenants",
            headers={"Authorization": "Bearer fake"},
            json={"name": "X", "slug": "x", "kind": "migrate"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 422


def test_create_requires_auth(auth_on: None) -> None:
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/tenants", json={"name": "X", "slug": "x", "kind": "personal"})
    assert r.status_code == 401
