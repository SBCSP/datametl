"""License token verify/issue + entitlement gates (no DB, no Stripe)."""
from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

# Ensure env before app imports (conftest also sets these).
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Clear bypass so tests control it explicitly.
os.environ.pop("DATAMETL_LICENSE_DEV_BYPASS", None)

from app.license.entitlements import COMMUNITY_MEL_LIMIT, Tier, get_entitlements
from app.license.gates import require_engine_allowed, require_mel_approval_choice, require_pro
from app.license.keys import generate_keypair_b64url, load_public_key
from app.license.token import LicenseError, LicensePayload, issue_license, verify_license


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture()
def signing_env(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Ephemeral keypair; override LICENSE_PUBLIC_KEY + LICENSE_SIGNING_KEY for this test."""
    priv, pub = generate_keypair_b64url()
    monkeypatch.setenv("LICENSE_SIGNING_KEY", priv)
    monkeypatch.setenv("LICENSE_PUBLIC_KEY", pub)
    monkeypatch.delenv("DATAMETL_LICENSE_DEV_BYPASS", raising=False)
    # Reload settings cache? entitlements reads cfg.license_dev_bypass once via settings object.
    # config.settings is a module-level singleton loaded at import — patch the attribute.
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)
    return priv, pub


def test_issue_and_verify_roundtrip(signing_env: tuple[str, str]) -> None:
    payload = LicensePayload(
        tier="pro",
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None,
        email="ops@example.com",
    )
    token = issue_license(payload)
    assert token.startswith("dmtl1.")
    got = verify_license(token)
    assert got.tier == "pro"
    assert got.email == "ops@example.com"
    assert got.expires_at is None


def test_invalid_signature_rejected(signing_env: tuple[str, str]) -> None:
    payload = LicensePayload(tier="pro", issued_at=datetime.now(UTC))
    token = issue_license(payload)
    parts = token.split(".")
    # Tamper with payload
    bad_body = _b64url(json.dumps({"tier": "pro", "issued_at": "2026-01-01T00:00:00Z"}).encode())
    bad = f"{parts[0]}.{bad_body}.{parts[2]}"
    with pytest.raises(LicenseError, match="signature"):
        verify_license(bad)


def test_expired_license_rejected(signing_env: tuple[str, str]) -> None:
    payload = LicensePayload(
        tier="pro",
        issued_at=datetime(2025, 1, 1, tzinfo=UTC),
        expires_at=datetime(2025, 6, 1, tzinfo=UTC),
    )
    token = issue_license(payload)
    with pytest.raises(LicenseError, match="expired"):
        verify_license(token, now=datetime(2026, 1, 1, tzinfo=UTC))


def test_malformed_token_rejected(signing_env: tuple[str, str]) -> None:
    with pytest.raises(LicenseError):
        verify_license("not-a-license")
    with pytest.raises(LicenseError):
        verify_license("")


def test_dev_bypass_is_pro(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", True)
    ents = get_entitlements(db=None)
    assert ents.is_pro
    assert ents.info.source == "dev_bypass"
    assert ents.allows_engine("mysql")
    assert ents.allows_engine("mssql")
    assert ents.effective_mel_tool_approval("auto") == "auto"


def test_community_forces_mel_always(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)
    ents = get_entitlements(db=None)
    assert ents.tier == Tier.community
    assert ents.effective_mel_tool_approval("auto") == "always"
    assert ents.effective_mel_tool_approval("run_sql_only") == "always"
    assert not ents.allows_engine("mysql")
    assert ents.allows_engine("postgres")
    assert COMMUNITY_MEL_LIMIT


def test_gates_block_mysql_on_community(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", False)
    db = MagicMock()
    # get_license_key path: patch get_entitlements via no key — use entitlements with db=None style
    # require_engine_allowed calls get_entitlements(db) which reads settings_store.
    # Mock: make get_license_key return None via patching.
    monkeypatch.setattr("app.settings_store.get_license_key", lambda _db: None)

    with pytest.raises(HTTPException) as ei:
        require_engine_allowed(db, "mysql")
    assert ei.value.status_code == 402

    require_engine_allowed(db, "postgres")  # ok

    with pytest.raises(HTTPException) as ei2:
        require_mel_approval_choice(db, "auto")
    assert ei2.value.status_code == 402

    require_mel_approval_choice(db, "always")  # ok on community

    with pytest.raises(HTTPException) as ei3:
        require_pro(db, feature="Ambient Mel autosend")
    assert ei3.value.status_code == 402


def test_gates_allow_when_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "license_dev_bypass", True)
    db = MagicMock()
    require_engine_allowed(db, "mssql")
    require_mel_approval_choice(db, "auto")
    require_pro(db, feature="anything")


def test_embedded_public_key_loads() -> None:
    # Smoke: default embedded key is a valid Ed25519 public key
    key = load_public_key()
    assert key is not None
