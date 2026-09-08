"""Offline-verifiable DataMETL license keys (Ed25519). Stripe secrets are optional vendor-issuer only.

Phase 1 product model:
- Community (no key): migrate/introspect/compare/verify + Mel with tool approval forced to ``always``.
- Pro (signed key or DATAMETL_LICENSE_DEV_BYPASS): full Mel approval modes + mysql/mssql engines.
- Team: entitlement stub only (no SSO in this batch).
"""
from __future__ import annotations

from app.license.entitlements import (
    COMMUNITY_MEL_LIMIT,
    Entitlements,
    LicenseInfo,
    Tier,
    get_entitlements,
)
from app.license.gates import (
    LICENSE_HTTP_STATUS,
    require_engine_allowed,
    require_mel_approval_choice,
    require_pro,
)
from app.license.token import LicenseError, LicensePayload, issue_license, verify_license

__all__ = [
    "COMMUNITY_MEL_LIMIT",
    "Entitlements",
    "LICENSE_HTTP_STATUS",
    "LicenseError",
    "LicenseInfo",
    "LicensePayload",
    "Tier",
    "get_entitlements",
    "issue_license",
    "require_engine_allowed",
    "require_mel_approval_choice",
    "require_pro",
    "verify_license",
]
