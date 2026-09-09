"""GitHub OAuth interfaces (stub for TENANT-SCHEMA; full wiring is GITHUB-OAUTH milestone).

Coordinate Knox for client secrets later. Do not store access/refresh tokens on
``OAuthIdentity.profile`` — that JSONB is non-secret profile only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class OAuthUserInfo:
    provider: str
    provider_subject: str
    email: str | None
    display_name: str | None
    profile: dict[str, object] | None = None


class OAuthProvider(Protocol):
    """Minimal provider contract for the next milestone."""

    name: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthUserInfo: ...


@dataclass
class GitHubOAuthConfig:
    """Env-backed config placeholder — values supplied in GITHUB-OAUTH milestone."""

    client_id: str = ""
    client_secret: str = ""  # from Knox / secret store — never commit
    redirect_uri: str = ""


class GitHubOAuthProvider:
    """Stub: raises until GITHUB-OAUTH milestone wires httpx + Knox secrets."""

    name = "github"

    def __init__(self, config: GitHubOAuthConfig | None = None) -> None:
        self.config = config or GitHubOAuthConfig()

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError(
            "GitHub OAuth authorize_url is stubbed; implement in GITHUB-OAUTH milestone"
        )

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthUserInfo:
        raise NotImplementedError(
            "GitHub OAuth exchange_code is stubbed; implement in GITHUB-OAUTH milestone"
        )


def link_oauth_identity_todo(user_id: UUID, info: OAuthUserInfo) -> None:
    """Placeholder for persisting OAuthIdentity after callback (GITHUB-OAUTH)."""
    raise NotImplementedError("link_oauth_identity_todo — GITHUB-OAUTH milestone")
