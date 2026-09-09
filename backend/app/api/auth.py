from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import auth
from app.api.schemas_io import AuthStatus, ChangePasswordRequest, LoginRequest, LoginResponse
from app.config import settings
from app.db import get_db
from app.tenancy.oauth import (
    GitHubOAuthError,
    GitHubOAuthProvider,
    github_oauth_configured,
    issue_oauth_state,
    link_oauth_identity,
    session_username_for_user,
    verify_oauth_state,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled.")
    if not settings.auth_legacy_basic:
        raise HTTPException(
            400,
            "AUTH_LEGACY_BASIC is disabled; use GitHub OAuth "
            "(GET /api/auth/github/start).",
        )
    if not auth.verify_login(db, payload.username, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
    token, exp = auth.issue_token(payload.username)
    return LoginResponse(token=token, username=payload.username, expires_at=exp)


@router.get("/status", response_model=AuthStatus)
def auth_status(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
) -> AuthStatus:
    """Public — the frontend gate uses this before login to decide whether to redirect."""
    oauth_on = bool(settings.auth_enabled and github_oauth_configured())
    legacy_on = bool(settings.auth_enabled and settings.auth_legacy_basic)
    if not settings.auth_enabled:
        return AuthStatus(
            auth_enabled=False,
            authenticated=True,
            username=None,
            github_oauth_enabled=False,
            legacy_basic_enabled=False,
        )
    user = auth.verify_token(_bearer(authorization) or "")
    return AuthStatus(
        auth_enabled=True,
        authenticated=user is not None,
        username=user,
        github_oauth_enabled=oauth_on,
        legacy_basic_enabled=legacy_on,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> None:
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled.")
    user = auth.verify_token(_bearer(authorization) or "")
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    if not auth.verify_login(db, user, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    auth.set_password(db, payload.new_password)


@router.get("/github/start", response_model=None)
def github_oauth_start(
    as_json: bool = Query(
        False,
        alias="json",
        description="If true, return authorize_url JSON instead of 302.",
    ),
) -> RedirectResponse | dict[str, str]:  # response_model=None (union of Response/dict)
    """Begin personal GitHub OAuth — 302 to GitHub, or JSON ``authorize_url`` when ``json=1``."""
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled.")
    provider = GitHubOAuthProvider()
    if not provider.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID, "
            "GITHUB_OAUTH_CLIENT_SECRET, and GITHUB_OAUTH_REDIRECT_URI.",
        )
    state = issue_oauth_state(provider="github")
    try:
        url = provider.authorize_url(state, provider.config.redirect_uri)
    except GitHubOAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if as_json:
        return {"authorize_url": url, "state": state}
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


def _prefer_html_oauth_landing(request: Request) -> bool:
    """Browsers send text/html; API clients / tests typically send application/json or */*."""
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" not in accept:
        return False
    html_pos = accept.find("text/html")
    json_pos = accept.find("application/json")
    if json_pos == -1:
        return True
    return html_pos < json_pos


@router.get("/github/callback", response_model=None)
def github_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
) -> LoginResponse | RedirectResponse:
    """Exchange GitHub code, link ``OAuthIdentity``, issue the same bearer session as login.

    Browser navigations (Accept includes text/html) 302 to ``/login#…`` so the FE can
    ``setToken``; API clients that prefer ``application/json`` still get ``LoginResponse``.
    """
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled.")
    if error:
        detail = error_description or error
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"GitHub OAuth error: {detail}")
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing code or state.")
    if not verify_oauth_state(state, provider="github"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state.")

    provider = GitHubOAuthProvider()
    if not provider.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID, "
            "GITHUB_OAUTH_CLIENT_SECRET, and GITHUB_OAUTH_REDIRECT_URI.",
        )
    try:
        info = provider.exchange_code(code, provider.config.redirect_uri)
    except GitHubOAuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user = link_oauth_identity(db, info)
    username = session_username_for_user(user, info)
    token, exp = auth.issue_token(username)
    payload = LoginResponse(token=token, username=username, expires_at=exp)
    if _prefer_html_oauth_landing(request):
        # Fragment keeps the token out of server/proxy access logs on the FE hop.
        frag = urlencode(
            {"token": payload.token, "username": payload.username, "expires_at": str(payload.expires_at)}
        )
        return RedirectResponse(url=f"/login#{frag}", status_code=status.HTTP_302_FOUND)
    return payload
