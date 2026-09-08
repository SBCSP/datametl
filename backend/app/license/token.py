"""Compact signed license tokens: dmtl1.<payload_b64url>.<sig_b64url>.

Payload is JSON (tier, issued_at, expires_at, optional email/seat/instance). Offline-verifiable
with the embedded Ed25519 public key — no network, no Stripe secret keys in the app.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature

from app.license.keys import load_public_key, load_signing_key

TOKEN_PREFIX = "dmtl1"
TierLiteral = Literal["pro", "team"]


class LicenseError(Exception):
    """Invalid, expired, or malformed license token."""


@dataclass(frozen=True)
class LicensePayload:
    tier: TierLiteral
    issued_at: datetime
    expires_at: datetime | None = None  # None = perpetual (v1)
    email: str | None = None
    seat_id: str | None = None
    instance_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "issued_at": _fmt(self.issued_at),
            "expires_at": _fmt(self.expires_at) if self.expires_at else None,
            "email": self.email,
            "seat_id": self.seat_id,
            "instance_id": self.instance_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LicensePayload:
        tier = data.get("tier")
        if tier not in ("pro", "team"):
            raise LicenseError(f"Unsupported license tier: {tier!r}")
        issued_raw = data.get("issued_at")
        if not issued_raw:
            raise LicenseError("License payload missing issued_at")
        expires_raw = data.get("expires_at")
        return cls(
            tier=tier,  # type: ignore[arg-type]
            issued_at=_parse_dt(issued_raw),
            expires_at=_parse_dt(expires_raw) if expires_raw else None,
            email=_opt_str(data.get("email")),
            seat_id=_opt_str(data.get("seat_id")),
            instance_id=_opt_str(data.get("instance_id")),
        )


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise LicenseError(f"Invalid datetime in license: {value!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def issue_license(payload: LicensePayload) -> str:
    """Sign a license token with LICENSE_SIGNING_KEY (issuer tooling)."""
    body = json.dumps(payload.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = load_signing_key().sign(body)
    return f"{TOKEN_PREFIX}.{_b64url_encode(body)}.{_b64url_encode(sig)}"


def verify_license(token: str, *, now: datetime | None = None) -> LicensePayload:
    """Verify signature + expiry. Raises LicenseError on any failure."""
    raw = (token or "").strip()
    if not raw:
        raise LicenseError("License key is empty")
    parts = raw.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseError("Malformed license key (expected dmtl1.<payload>.<sig>)")
    try:
        body = _b64url_decode(parts[1])
        sig = _b64url_decode(parts[2])
    except Exception as e:
        raise LicenseError("License key is not valid base64url") from e
    try:
        load_public_key().verify(sig, body)
    except InvalidSignature as e:
        raise LicenseError("Invalid license signature") from e
    except Exception as e:
        raise LicenseError(f"License verification failed: {e}") from e
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise LicenseError("License payload is not valid JSON") from e
    if not isinstance(data, dict):
        raise LicenseError("License payload must be a JSON object")
    payload = LicensePayload.from_dict(data)
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    if payload.expires_at is not None and clock > payload.expires_at:
        raise LicenseError(f"License expired at { _fmt(payload.expires_at) }")
    return payload
