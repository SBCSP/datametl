"""Legacy username/password sessions get a ``public.users`` row (onboarding gate fix).

Before this, only GitHub OAuth created users, so a legacy ``admin`` token hit
``GET /api/tenants/me`` → 403 "No local user" forever and the frontend gate looped.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.config import settings
from app.models.tenant_control import User
from app.tenancy.binding import ensure_user_for_subject


def _db_returning(user: object | None) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    result.all.return_value = []
    db.execute.return_value = result
    return db


def test_ensure_user_creates_row_when_missing() -> None:
    db = _db_returning(None)
    user = ensure_user_for_subject(db, " admin ")
    assert isinstance(user, User)
    assert user.display_name == "admin"
    assert user.email is None
    db.add.assert_called_once_with(user)
    db.commit.assert_called_once()


def test_ensure_user_returns_existing_without_insert() -> None:
    existing = MagicMock(spec=User)
    db = _db_returning(existing)
    assert ensure_user_for_subject(db, "admin") is existing
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_ensure_user_rejects_blank_subject() -> None:
    with pytest.raises(ValueError):
        ensure_user_for_subject(MagicMock(), "   ")


def test_tenants_me_provisions_legacy_user_for_existing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy token issued before login created users rows must still onboard, not 403."""
    from app.db import get_db
    from app.main import app

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    monkeypatch.setattr(settings, "auth_legacy_basic", True)

    db = _db_returning(None)
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    provisioned: list[str] = []

    def fake_ensure(_db: object, subject: str) -> MagicMock:
        provisioned.append(subject)
        return user

    monkeypatch.setattr("app.auth.verify_token", lambda t: "admin" if t else None)
    monkeypatch.setattr("app.api.tenants.auth_lib.get_username", lambda _db: "admin")
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda _db, _s: None)
    monkeypatch.setattr("app.api.tenants.ensure_user_for_subject", fake_ensure)

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.get("/api/tenants/me", headers={"Authorization": "Bearer fake"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200, r.text
    assert r.json() == {"needs_onboarding": True, "tenants": []}
    assert provisioned == ["admin"]


def test_tenants_me_still_403_for_unknown_non_legacy_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-provisioning is scoped to the configured legacy username only."""
    from app.db import get_db
    from app.main import app

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "tenant_enforce_enabled", True)
    monkeypatch.setattr(settings, "auth_legacy_basic", True)

    db = _db_returning(None)
    monkeypatch.setattr("app.auth.verify_token", lambda t: "someone-else" if t else None)
    monkeypatch.setattr("app.api.tenants.auth_lib.get_username", lambda _db: "admin")
    monkeypatch.setattr("app.api.tenants.resolve_user_for_subject", lambda _db, _s: None)
    monkeypatch.setattr(
        "app.api.tenants.ensure_user_for_subject",
        lambda _db, _s: pytest.fail("must not provision non-legacy subjects"),
    )

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        r = client.get("/api/tenants/me", headers={"Authorization": "Bearer fake"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 403
