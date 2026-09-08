"""Ed25519 public key for license verification.

The matching private key lives only in LICENSE_SIGNING_KEY (issuer machines / CI).
Never commit a signing private key. Override the embedded public key with LICENSE_PUBLIC_KEY
when rotating (base64url-encoded 32-byte raw Ed25519 public key).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# DEV / release-v1 public key (pair generated for Phase 1; private key is NOT in git).
# Generate a new pair: `python scripts/issue_license.py --gen-keypair`
_EMBEDDED_PUBLIC_KEY_B64URL = "m4X_8VCOIRSgjPqC1c4kaZyJ9f6g6uzeAK0kKG6IluE"


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.strip() + pad)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def load_public_key() -> Ed25519PublicKey:
    override = (os.environ.get("LICENSE_PUBLIC_KEY") or "").strip()
    raw = _b64url_decode(override) if override else _b64url_decode(_EMBEDDED_PUBLIC_KEY_B64URL)
    if len(raw) != 32:
        raise ValueError("LICENSE_PUBLIC_KEY must be a 32-byte Ed25519 public key (base64url)")
    return Ed25519PublicKey.from_public_bytes(raw)


def load_signing_key() -> Ed25519PrivateKey:
    """Private key from LICENSE_SIGNING_KEY — issuer tooling only, never required at runtime."""
    value = (os.environ.get("LICENSE_SIGNING_KEY") or "").strip()
    if not value:
        raise RuntimeError(
            "LICENSE_SIGNING_KEY is not set. Generate with "
            "`python scripts/issue_license.py --gen-keypair` and export the private key."
        )
    raw = _b64url_decode(value)
    if len(raw) != 32:
        raise ValueError("LICENSE_SIGNING_KEY must be a 32-byte Ed25519 private key (base64url)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def embedded_public_key_b64url() -> str:
    return _EMBEDDED_PUBLIC_KEY_B64URL


def generate_keypair_b64url() -> tuple[str, str]:
    """Return (private_b64url, public_b64url) for local issuer setup."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes_raw()
    pub_raw = priv.public_key().public_bytes_raw()
    return _b64url_encode(priv_raw), _b64url_encode(pub_raw)
