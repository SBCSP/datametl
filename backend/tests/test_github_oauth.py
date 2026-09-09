"""GitHub OAuth (GITHUB-OAUTH) — mocked httpx, no network."""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

# Env before app imports (conftest also sets these).
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.config import settings
from app.tenancy.oauth import (
    GitHubOAuthConfig,
    GitHubOAuthError,
    GitHubOAuthProvider,
    OAuthUserInfo,
    issue_oauth_state,
    link_oauth_identity,
    session_username_for_user,
    verify_oauth_state,
)


@pytest.fixture()
def github_settings(monkeypatch: pytest.MonkeyPatch) -> GitHubOAuthConfig:
    cfg = GitHubOAuthConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8001/api/auth/github/callback",
    )
    monkeypatch.setattr(settings, "github_oauth_client_id", cfg.client_id)
    monkeypatch.setattr(settings, "github_oauth_client_secret", cfg.client_secret)
    monkeypatch.setattr(settings, "github_oauth_redirect_uri", cfg.redirect_uri)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_legacy_basic", True)
    return cfg


def _mock_client(handlers: dict[str, httpx.Response]) -> httpx.Client:
    """Minimal transport that maps URL → Response (no network)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url).split("?")[0]
        if key not in handlers:
            return httpx.Response(404, json={"message": f"unexpected URL {key}"})
        return handlers[key]

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_config_empty_means_disabled() -> None:
    cfg = GitHubOAuthConfig()
    assert not cfg.is_configured()
    provider = GitHubOAuthProvider(cfg)
    with pytest.raises(GitHubOAuthError, match="GITHUB_OAUTH_CLIENT_ID"):
        provider.authorize_url("state", "http://example/callback")
    with pytest.raises(GitHubOAuthError, match="GITHUB_OAUTH_CLIENT_ID"):
        provider.exchange_code("code", "http://example/callback")


def test_authorize_url_contains_client_id_and_state(github_settings: GitHubOAuthConfig) -> None:
    provider = GitHubOAuthProvider(github_settings)
    url = provider.authorize_url("abcSTATE", github_settings.redirect_uri)
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=test-client-id" in url
    assert "state=abcSTATE" in url
    assert "redirect_uri=" in url
    assert "scope=" in url


def test_exchange_code_mocked_httpx(github_settings: GitHubOAuthConfig) -> None:
    client = _mock_client(
        {
            "https://github.com/login/oauth/access_token": httpx.Response(
                200,
                json={"access_token": "gho_test_token", "token_type": "bearer", "scope": "read:user"},
            ),
            "https://api.github.com/user": httpx.Response(
                200,
                json={
                    "id": 4242,
                    "login": "octocat",
                    "name": "The Octocat",
                    "email": None,
                    "avatar_url": "https://avatars.example/o.png",
                    "html_url": "https://github.com/octocat",
                },
            ),
            "https://api.github.com/user/emails": httpx.Response(
                200,
                json=[
                    {"email": "octocat@users.noreply.github.com", "primary": False, "verified": True},
                    {"email": "octo@example.com", "primary": True, "verified": True},
                ],
            ),
        }
    )
    provider = GitHubOAuthProvider(github_settings, client=client)
    info = provider.exchange_code("one-time-code", github_settings.redirect_uri)
    assert info.provider == "github"
    assert info.provider_subject == "4242"
    assert info.email == "octo@example.com"
    assert info.display_name == "The Octocat"
    assert info.profile is not None
    assert info.profile.get("login") == "octocat"
    # Must never look like a token store.
    assert "access_token" not in (info.profile or {})


def test_exchange_code_token_error(github_settings: GitHubOAuthConfig) -> None:
    client = _mock_client(
        {
            "https://github.com/login/oauth/access_token": httpx.Response(
                200,
                json={"error": "bad_verification_code", "error_description": "code expired"},
            ),
        }
    )
    provider = GitHubOAuthProvider(github_settings, client=client)
    with pytest.raises(GitHubOAuthError, match="code expired"):
        provider.exchange_code("bad", github_settings.redirect_uri)


def test_oauth_state_roundtrip() -> None:
    state = issue_oauth_state(provider="github")
    assert verify_oauth_state(state, provider="github")
    assert not verify_oauth_state(state, provider="other")
    assert not verify_oauth_state(state[:-1] + ("x" if state[-1] != "x" else "y"))


def test_link_oauth_identity_creates_user_and_row() -> None:
    from app.models.tenant_control import OAuthIdentity, User

    info = OAuthUserInfo(
        provider="github",
        provider_subject="99",
        email="a@example.com",
        display_name="Ada",
        profile={"login": "ada"},
    )
    db = MagicMock()
    # First select (OAuthIdentity by subject) → None; second (User by email) → None
    db.execute.return_value.scalar_one_or_none.side_effect = [None, None]
    created: dict[str, Any] = {}

    def add(obj: Any) -> None:
        if isinstance(obj, User):
            obj.id = uuid4()
            created["user"] = obj
        elif isinstance(obj, OAuthIdentity):
            created["identity"] = obj

    db.add.side_effect = add
    db.get.return_value = None

    user = link_oauth_identity(db, info)
    assert user is created["user"]
    assert user.email == "a@example.com"
    assert created["identity"].provider == "github"
    assert created["identity"].provider_subject == "99"
    assert created["identity"].profile == {"login": "ada"}
    db.commit.assert_called()


def test_link_oauth_identity_reuses_existing() -> None:
    from app.models.tenant_control import User

    existing_user = User(email="a@example.com", display_name="Ada")
    existing_user.id = uuid4()
    identity = MagicMock()
    identity.user_id = existing_user.id
    identity.profile = None

    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = identity
    db.get.return_value = existing_user

    info = OAuthUserInfo(
        provider="github",
        provider_subject="99",
        email="a@example.com",
        display_name="Ada",
        profile={"login": "ada"},
    )
    user = link_oauth_identity(db, info)
    assert user is existing_user
    assert identity.profile == {"login": "ada"}
    db.add.assert_not_called()


def test_session_username_prefers_email() -> None:
    from app.models.tenant_control import User

    u = User(email="a@example.com", display_name="Ada")
    u.id = uuid4()
    assert session_username_for_user(u) == "a@example.com"


def test_github_start_redirect(github_settings: GitHubOAuthConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/auth/github/start", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize?")


def test_github_start_json(github_settings: GitHubOAuthConfig) -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/auth/github/start", params={"json": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "authorize_url" in body
    assert "state" in body
    assert verify_oauth_state(body["state"])


def test_github_start_503_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "github_oauth_client_id", "")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "")
    monkeypatch.setattr(settings, "github_oauth_redirect_uri", "")
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/auth/github/start", follow_redirects=False)
    assert resp.status_code == 503
    assert "GITHUB_OAUTH_CLIENT_ID" in resp.json()["detail"]


def test_github_callback_links_and_issues_token(
    github_settings: GitHubOAuthConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app
    from app.models.tenant_control import User

    info = OAuthUserInfo(
        provider="github",
        provider_subject="7",
        email="cb@example.com",
        display_name="Callback User",
        profile={"login": "cb"},
    )
    user = User(email=info.email, display_name=info.display_name)
    user.id = uuid4()

    monkeypatch.setattr(
        "app.api.auth.GitHubOAuthProvider.exchange_code",
        lambda self, code, redirect_uri: info,
    )
    monkeypatch.setattr("app.api.auth.link_oauth_identity", lambda db, i: user)

    state = issue_oauth_state()
    client = TestClient(app)
    resp = client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": state},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "cb@example.com"
    assert body["token"]
    assert body["expires_at"] > 0

    state2 = issue_oauth_state()
    html = client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": state2},
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert html.status_code == 302
    loc = html.headers["location"]
    assert loc.startswith("/login#")
    assert "token=" in loc


def test_github_callback_rejects_bad_state(github_settings: GitHubOAuthConfig) -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.get(
        "/api/auth/github/callback",
        params={"code": "ok", "state": "not.valid"},
    )
    assert resp.status_code == 400
    assert "state" in resp.json()["detail"].lower()


def test_auth_status_reports_oauth_flags(github_settings: GitHubOAuthConfig) -> None:
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_enabled"] is True
    assert body["github_oauth_enabled"] is True
    assert body["legacy_basic_enabled"] is True


def test_legacy_login_still_works_with_oauth_configured(
    github_settings: GitHubOAuthConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    monkeypatch.setattr("app.api.auth.auth.verify_login", lambda db, u, p: u == "admin" and p == "pw")
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_legacy_login_blocked_when_legacy_off(
    github_settings: GitHubOAuthConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_legacy_basic", False)
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert resp.status_code == 400
    assert "AUTH_LEGACY_BASIC" in resp.json()["detail"]
