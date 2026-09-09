"""GitHub OAuth (personal v1) — authorize URL + code exchange via httpx.

Secrets come from env (GITHUB_OAUTH_*). Empty values mean the feature is disabled;
callers get clear errors. Do not store access/refresh tokens on
``OAuthIdentity.profile`` — that JSONB is non-secret profile only.

Coordinate Knox / a secret store for production client secrets later.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_control import OAuthIdentity, User

log = logging.getLogger("datametl.tenancy.oauth")

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_URL = "https://api.github.com/user/emails"
DEFAULT_SCOPES = "read:user user:email"
_STATE_TTL_SECONDS = 600


class GitHubOAuthError(RuntimeError):
    """Raised when GitHub OAuth is misconfigured or the IdP rejects the exchange."""


@dataclass(frozen=True)
class OAuthUserInfo:
    provider: str
    provider_subject: str
    email: str | None
    display_name: str | None
    profile: dict[str, object] | None = None


class OAuthProvider(Protocol):
    """Minimal provider contract."""

    name: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthUserInfo: ...


@dataclass
class GitHubOAuthConfig:
    """Env-backed GitHub OAuth app settings (names only — never commit secrets)."""

    client_id: str = ""
    client_secret: str = ""  # from Knox / secret store — never commit
    redirect_uri: str = ""

    @classmethod
    def from_settings(cls) -> GitHubOAuthConfig:
        from app.config import settings

        return cls(
            client_id=(settings.github_oauth_client_id or "").strip(),
            client_secret=(settings.github_oauth_client_secret or "").strip(),
            redirect_uri=(settings.github_oauth_redirect_uri or "").strip(),
        )

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


def github_oauth_configured() -> bool:
    """True when all three GITHUB_OAUTH_* env-backed settings are non-empty."""
    return GitHubOAuthConfig.from_settings().is_configured()


class GitHubOAuthProvider:
    """Personal GitHub OAuth v1 using httpx (no network in unit tests — inject client)."""

    name = "github"

    def __init__(
        self,
        config: GitHubOAuthConfig | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config or GitHubOAuthConfig.from_settings()
        self._client = client
        self._timeout = timeout

    def is_configured(self) -> bool:
        return self.config.is_configured()

    def _require_configured(self) -> None:
        if not self.config.is_configured():
            raise GitHubOAuthError(
                "GitHub OAuth is disabled: set GITHUB_OAUTH_CLIENT_ID, "
                "GITHUB_OAUTH_CLIENT_SECRET, and GITHUB_OAUTH_REDIRECT_URI."
            )

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require_configured()
        uri = (redirect_uri or self.config.redirect_uri).strip()
        if not uri:
            raise GitHubOAuthError("redirect_uri is required for GitHub authorize URL.")
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": uri,
            "state": state,
            "scope": DEFAULT_SCOPES,
            "allow_signup": "true",
        }
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthUserInfo:
        self._require_configured()
        if not (code or "").strip():
            raise GitHubOAuthError("Missing OAuth authorization code.")
        uri = (redirect_uri or self.config.redirect_uri).strip()
        if not uri:
            raise GitHubOAuthError("redirect_uri is required for code exchange.")

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            token = self._exchange_token(client, code.strip(), uri)
            user_payload = self._fetch_user(client, token)
            email = self._pick_email(client, token, user_payload)
        finally:
            if owns_client:
                client.close()

        subject = str(user_payload.get("id") or "").strip()
        if not subject:
            raise GitHubOAuthError("GitHub user payload missing id.")

        login = str(user_payload.get("login") or "").strip() or None
        name = str(user_payload.get("name") or "").strip() or None
        display = name or login
        profile: dict[str, object] = {
            "login": login,
            "avatar_url": user_payload.get("avatar_url"),
            "html_url": user_payload.get("html_url"),
            "name": name,
        }
        # Drop Nones for a compact non-secret profile stub.
        profile = {k: v for k, v in profile.items() if v is not None}

        return OAuthUserInfo(
            provider=self.name,
            provider_subject=subject,
            email=email,
            display_name=display,
            profile=profile,
        )

    def _exchange_token(self, client: httpx.Client, code: str, redirect_uri: str) -> str:
        resp = client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if resp.status_code >= 400:
            raise GitHubOAuthError(
                f"GitHub token endpoint returned HTTP {resp.status_code}."
            )
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GitHubOAuthError("GitHub token endpoint returned non-JSON.") from exc
        if not isinstance(body, dict):
            raise GitHubOAuthError("GitHub token endpoint returned unexpected payload.")
        if body.get("error"):
            desc = body.get("error_description") or body.get("error")
            raise GitHubOAuthError(f"GitHub token error: {desc}")
        token = str(body.get("access_token") or "").strip()
        if not token:
            raise GitHubOAuthError("GitHub token endpoint omitted access_token.")
        return token

    def _fetch_user(self, client: httpx.Client, access_token: str) -> dict[str, Any]:
        resp = client.get(
            GITHUB_USER_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if resp.status_code >= 400:
            raise GitHubOAuthError(f"GitHub user API returned HTTP {resp.status_code}.")
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GitHubOAuthError("GitHub user API returned non-JSON.") from exc
        if not isinstance(body, dict):
            raise GitHubOAuthError("GitHub user API returned unexpected payload.")
        return body

    def _pick_email(
        self, client: httpx.Client, access_token: str, user_payload: dict[str, Any]
    ) -> str | None:
        # Prefer public email on the user object when present.
        public = user_payload.get("email")
        if isinstance(public, str) and public.strip():
            return public.strip()

        resp = client.get(
            GITHUB_USER_EMAILS_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if resp.status_code >= 400:
            log.info("GitHub emails API HTTP %s — continuing without email", resp.status_code)
            return None
        try:
            rows = resp.json()
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        primary_verified: str | None = None
        any_verified: str | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            addr = row.get("email")
            if not isinstance(addr, str) or not addr.strip():
                continue
            if row.get("verified") is True:
                if row.get("primary") is True:
                    primary_verified = addr.strip()
                    break
                if any_verified is None:
                    any_verified = addr.strip()
        return primary_verified or any_verified


# --- CSRF state (HMAC-signed, short-lived) ---

def issue_oauth_state(*, provider: str = "github") -> str:
    """Return a signed opaque state string for the OAuth round-trip."""
    import hashlib
    import hmac
    import json

    from app import auth as auth_lib

    exp = int(time.time()) + _STATE_TTL_SECONDS
    nonce = secrets.token_urlsafe(16)
    body = auth_lib._b64u(  # noqa: SLF001 — shared b64url helper
        json.dumps({"p": provider, "n": nonce, "exp": exp}, separators=(",", ":")).encode()
    )
    sig = auth_lib._b64u(  # noqa: SLF001
        hmac.new(auth_lib._sigkey(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_oauth_state(state: str, *, provider: str = "github") -> bool:
    """Validate signed OAuth state; False on tamper / expiry / provider mismatch."""
    import hashlib
    import hmac
    import json

    from app import auth as auth_lib

    try:
        body, sig = state.split(".", 1)
        expected = auth_lib._b64u(  # noqa: SLF001
            hmac.new(auth_lib._sigkey(), body.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(auth_lib._b64u_decode(body))  # noqa: SLF001
        if int(payload.get("exp", 0)) < int(time.time()):
            return False
        if str(payload.get("p") or "") != provider:
            return False
        return bool(payload.get("n"))
    except Exception:
        return False


def link_oauth_identity(db: Session, info: OAuthUserInfo) -> User:
    """Find or create ``User`` + ``OAuthIdentity`` for the provider subject.

    Never stores OAuth tokens on ``OAuthIdentity.profile``.
    """
    if info.provider != "github":
        raise ValueError(f"unsupported OAuth provider: {info.provider}")
    if not (info.provider_subject or "").strip():
        raise ValueError("provider_subject is required")

    existing = db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == info.provider,
            OAuthIdentity.provider_subject == info.provider_subject,
        )
    ).scalar_one_or_none()

    if existing is not None:
        user = db.get(User, existing.user_id)
        if user is None:
            raise RuntimeError("OAuthIdentity references missing user")
        if info.profile is not None:
            existing.profile = dict(info.profile)
        if info.email and not user.email:
            user.email = info.email
        if info.display_name and not user.display_name:
            user.display_name = info.display_name
        db.commit()
        db.refresh(user)
        return user

    matched: User | None = None
    if info.email:
        matched = db.execute(select(User).where(User.email == info.email)).scalar_one_or_none()
    if matched is None:
        matched = User(email=info.email, display_name=info.display_name)
        db.add(matched)
        db.flush()
    elif info.display_name and not matched.display_name:
        matched.display_name = info.display_name

    db.add(
        OAuthIdentity(
            user_id=matched.id,
            provider=info.provider,
            provider_subject=info.provider_subject,
            profile=dict(info.profile) if info.profile else None,
        )
    )
    db.commit()
    db.refresh(matched)
    return matched


def link_oauth_identity_todo(user_id: UUID, info: OAuthUserInfo) -> None:
    """Deprecated stub kept for import compatibility — use ``link_oauth_identity``."""
    raise NotImplementedError(
        "link_oauth_identity_todo is retired; use link_oauth_identity(db, info)"
    )


def session_username_for_user(user: User, info: OAuthUserInfo | None = None) -> str:
    """Stable bearer-token subject compatible with existing ``auth.issue_token``."""
    if user.email:
        return user.email
    if user.display_name:
        return user.display_name
    if info and info.profile and isinstance(info.profile.get("login"), str):
        return f"github:{info.profile['login']}"
    return f"github:{user.id}"
