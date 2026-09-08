#!/usr/bin/env python3
"""Issue a signed DataMETL Pro (or Team stub) license key.

Requires LICENSE_SIGNING_KEY (base64url 32-byte Ed25519 private key) in the environment.
Never commit that key. Generate a pair with --gen-keypair, embed the public key in
backend/app/license/keys.py (or set LICENSE_PUBLIC_KEY), and keep the private key offline.

Examples:
  python scripts/issue_license.py --gen-keypair
  LICENSE_SIGNING_KEY=... python scripts/issue_license.py --email you@example.com
  LICENSE_SIGNING_KEY=... python scripts/issue_license.py --tier pro --expires 2027-01-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Allow running from repo root or inside the backend container (backend mounted at /app).
_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "backend",  # repo: scripts/../backend
    Path("/app"),  # docker: backend workdir
]
for _backend in _CANDIDATES:
    if (_backend / "app" / "license").is_dir() and str(_backend) not in sys.path:
        sys.path.insert(0, str(_backend))
        break


def _parse_expires(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.lower() in {"none", "perpetual", "never"}:
        return None
    if text.startswith("+"):
        # +90d / +1y convenience
        unit = text[-1].lower()
        amount = int(text[1:-1])
        now = datetime.now(UTC)
        if unit == "d":
            return now + timedelta(days=amount)
        if unit == "y":
            return now + timedelta(days=365 * amount)
        raise SystemExit(f"Unsupported relative expiry: {value}")
    if len(text) == 10:
        text = text + "T23:59:59Z"
    text = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a DataMETL signed license key")
    parser.add_argument("--gen-keypair", action="store_true", help="Print a new Ed25519 keypair and exit")
    parser.add_argument("--tier", choices=["pro", "team"], default="pro")
    parser.add_argument("--email", default=None)
    parser.add_argument("--seat-id", default=None)
    parser.add_argument("--instance-id", default=None)
    parser.add_argument(
        "--expires",
        default=None,
        help="ISO date/datetime, +90d / +1y, or 'perpetual' (default: perpetual)",
    )
    args = parser.parse_args()

    if args.gen_keypair:
        from app.license.keys import generate_keypair_b64url

        priv, pub = generate_keypair_b64url()
        print("# Add the public key to backend/app/license/keys.py (_EMBEDDED_PUBLIC_KEY_B64URL)")
        print("# or set LICENSE_PUBLIC_KEY. Keep the private key in LICENSE_SIGNING_KEY only.")
        print(f"LICENSE_SIGNING_KEY={priv}")
        print(f"LICENSE_PUBLIC_KEY={pub}")
        return 0

    from app.license.token import LicensePayload, issue_license

    payload = LicensePayload(
        tier=args.tier,
        issued_at=datetime.now(UTC),
        expires_at=_parse_expires(args.expires),
        email=args.email,
        seat_id=args.seat_id,
        instance_id=args.instance_id,
    )
    token = issue_license(payload)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
