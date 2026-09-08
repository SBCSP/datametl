"""Resolve Community vs Pro entitlements from stored license + env bypass."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from sqlalchemy.orm import Session

from app.config import settings as cfg
from app.license.token import LicenseError, LicensePayload, verify_license

# Community Mel limit (Phase 1): force tool approval to "always".
# Pro removes this cap so operators can choose run_sql_only / auto.
COMMUNITY_MEL_LIMIT = (
    "Mel tool approval is fixed to 'always' on Community. "
    "Activate a Pro license to choose run_sql_only or auto."
)

PRO_ENGINES = frozenset({"mysql", "mssql"})
FREE_ENGINES = frozenset({"postgres"})


class Tier(str, Enum):
    community = "community"
    pro = "pro"
    team = "team"  # stub entitlement only — no SSO in Phase 1


@dataclass(frozen=True)
class LicenseInfo:
    tier: Tier
    active: bool
    source: Literal["none", "key", "dev_bypass"]
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    email: str | None = None
    seat_id: str | None = None
    instance_id: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Entitlements:
    info: LicenseInfo

    @property
    def tier(self) -> Tier:
        return self.info.tier

    @property
    def is_pro(self) -> bool:
        return self.info.tier in (Tier.pro, Tier.team)

    def allows_engine(self, engine: str) -> bool:
        eng = (engine or "").lower().strip()
        if eng in FREE_ENGINES:
            return True
        if eng in PRO_ENGINES:
            return self.is_pro
        return False

    def effective_mel_tool_approval(self, stored: str) -> str:
        """Community forces always; Pro/Team return the stored preference."""
        if not self.is_pro:
            return "always"
        return stored

    def can_choose_mel_approval(self) -> bool:
        return self.is_pro

    def allows_external_mcp(self) -> bool:
        """External FastMCP (Cursor/Claude Desktop) is Pro-only; Mel in-app stays Community."""
        return self.is_pro


def _community(message: str | None = None) -> Entitlements:
    return Entitlements(
        LicenseInfo(
            tier=Tier.community,
            active=False,
            source="none",
            message=message,
        )
    )


def _from_payload(payload: LicensePayload, *, source: Literal["key", "dev_bypass"]) -> Entitlements:
    tier = Tier.team if payload.tier == "team" else Tier.pro
    return Entitlements(
        LicenseInfo(
            tier=tier,
            active=True,
            source=source,
            issued_at=payload.issued_at,
            expires_at=payload.expires_at,
            email=payload.email,
            seat_id=payload.seat_id,
            instance_id=payload.instance_id,
        )
    )


def get_entitlements(db: Session | None = None) -> Entitlements:
    """Resolve current entitlements. db is optional when only checking DEV_BYPASS."""
    if cfg.license_dev_bypass:
        # Synthetic perpetual Pro for local docker without pasting a key.
        from datetime import UTC

        return _from_payload(
            LicensePayload(tier="pro", issued_at=datetime.now(UTC), expires_at=None, email="dev-bypass"),
            source="dev_bypass",
        )

    if db is None:
        return _community()

    from app.settings_store import get_license_key

    token = get_license_key(db)
    if not token:
        return _community()
    try:
        payload = verify_license(token)
    except LicenseError as e:
        return _community(message=str(e))
    return _from_payload(payload, source="key")
