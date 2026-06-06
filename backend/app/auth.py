"""Simple single-user auth: password hashing, signed bearer tokens, and a credential store.

Enabled only when AUTH_ENABLED is set (see config). The credential (username + scrypt password
hash) lives Fernet-encrypted in the app_settings KV table — reusing the same `vault` and pattern as
the Anthropic key. The session token is an HMAC-signed `{sub, exp}` blob; the signing key is derived
from ENCRYPTION_KEY so there's no extra mandatory secret. Stdlib only — no new dependencies.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import vault
from app.models.app_setting import AppSetting

log = logging.getLogger("datametl.auth")

_CRED_KEY = "auth_credential"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN = 2**14, 8, 1, 32


# --- password hashing (scrypt) ---

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, hash_b64 = stored.split("$", 2)
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(
            password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=len(expected)
        )
        return hmac.compare_digest(dk, expected)
    except Exception:  # malformed stored hash → treat as no match
        return False


# --- signed bearer token ---

def _sigkey() -> bytes:
    return hashlib.sha256(b"datametl-auth-v1" + settings.encryption_key.encode()).digest()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(username: str) -> tuple[str, int]:
    """Return (token, expires_at_epoch)."""
    exp = int(time.time()) + settings.auth_token_ttl_hours * 3600
    body = _b64u(json.dumps({"sub": username, "exp": exp}, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(_sigkey(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", exp


def verify_token(token: str) -> str | None:
    """Return the username if the token is valid and unexpired, else None."""
    try:
        body, sig = token.split(".", 1)
        expected = _b64u(hmac.new(_sigkey(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64u_decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None
    except Exception:
        return None


# --- credential store (app_settings) ---

def _load(db: Session) -> dict[str, Any] | None:
    row = db.get(AppSetting, _CRED_KEY)
    return vault.decrypt(row.encrypted_value) if row is not None else None


def _save(db: Session, username: str, password_hash: str) -> None:
    enc = vault.encrypt({"username": username, "password_hash": password_hash})
    row = db.get(AppSetting, _CRED_KEY)
    if row is None:
        db.add(AppSetting(key=_CRED_KEY, encrypted_value=enc))
    else:
        row.encrypted_value = enc
    db.commit()


def ensure_seeded(db: Session) -> None:
    """Create the credential on first run from AUTH_USERNAME/AUTH_PASSWORD env."""
    if db.get(AppSetting, _CRED_KEY) is not None:
        return
    username = (settings.auth_username or "admin").strip() or "admin"
    password = settings.auth_password
    if not password:
        password = "admin"
        log.warning(
            "AUTH_ENABLED but no AUTH_PASSWORD set — seeding default login '%s' / 'admin'. "
            "Change it in Settings or set AUTH_PASSWORD.",
            username,
        )
    _save(db, username, hash_password(password))


def get_username(db: Session) -> str:
    ensure_seeded(db)
    cred = _load(db)
    return str(cred["username"]) if cred else (settings.auth_username or "admin")


def verify_login(db: Session, username: str, password: str) -> bool:
    ensure_seeded(db)
    cred = _load(db)
    if not cred:
        return False
    return hmac.compare_digest(str(cred["username"]), username) and verify_password(
        password, str(cred["password_hash"])
    )


def set_password(db: Session, new_password: str) -> None:
    ensure_seeded(db)
    cred = _load(db)
    username = str(cred["username"]) if cred else (settings.auth_username or "admin")
    _save(db, username, hash_password(new_password))
