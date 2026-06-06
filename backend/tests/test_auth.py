"""Pure-logic tests for password hashing + signed bearer tokens (no DB)."""
from __future__ import annotations

import base64
import json
import time as _time

from app import auth


def test_password_hash_roundtrip() -> None:
    h = auth.hash_password("s3cret-pw")
    assert h.startswith("scrypt$")
    assert auth.verify_password("s3cret-pw", h)
    assert not auth.verify_password("wrong", h)


def test_verify_password_rejects_malformed() -> None:
    assert not auth.verify_password("anything", "not-a-valid-hash")


def test_token_roundtrip() -> None:
    token, exp = auth.issue_token("admin")
    assert auth.verify_token(token) == "admin"
    assert exp > int(_time.time())


def test_token_rejects_bad_signature() -> None:
    token, _ = auth.issue_token("admin")
    body, _sig = token.split(".", 1)
    assert auth.verify_token(body + ".tampered") is None


def test_token_rejects_tampered_payload() -> None:
    token, _ = auth.issue_token("admin")
    _body, sig = token.split(".", 1)
    forged = base64.urlsafe_b64encode(
        json.dumps({"sub": "hacker", "exp": 9999999999}).encode()
    ).rstrip(b"=").decode()
    assert auth.verify_token(f"{forged}.{sig}") is None


def test_token_expired(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    token, _ = auth.issue_token("admin")
    monkeypatch.setattr(auth.time, "time", lambda: _time.time() + 10**9)
    assert auth.verify_token(token) is None
