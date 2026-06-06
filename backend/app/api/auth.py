from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app import auth
from app.api.schemas_io import AuthStatus, ChangePasswordRequest, LoginRequest, LoginResponse
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    if not settings.auth_enabled:
        raise HTTPException(400, "Authentication is disabled.")
    if not auth.verify_login(db, payload.username, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
    token, exp = auth.issue_token(payload.username)
    return LoginResponse(token=token, username=payload.username, expires_at=exp)


@router.get("/status", response_model=AuthStatus)
def auth_status(
    db: Session = Depends(get_db), authorization: str | None = Header(default=None)
) -> AuthStatus:
    """Public — the frontend gate uses this before login to decide whether to redirect."""
    if not settings.auth_enabled:
        return AuthStatus(auth_enabled=False, authenticated=True, username=None)
    user = auth.verify_token(_bearer(authorization) or "")
    return AuthStatus(auth_enabled=True, authenticated=user is not None, username=user)


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
