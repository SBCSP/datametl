"""HTTP feature gates for Pro engines and Mel approval choices."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.license.entitlements import COMMUNITY_MEL_LIMIT, PRO_ENGINES, get_entitlements

# Prefer 402 so the UI can surface an upgrade / activate-license path.
LICENSE_HTTP_STATUS = 402


def require_pro(db: Session, *, feature: str) -> None:
    ents = get_entitlements(db)
    if ents.is_pro:
        return
    raise HTTPException(
        LICENSE_HTTP_STATUS,
        f"{feature} requires DataMETL Pro. Activate a license key in Settings "
        "(or set DATAMETL_LICENSE_DEV_BYPASS=true for local docker).",
    )


def require_engine_allowed(db: Session, engine: str) -> None:
    eng = (engine or "").lower().strip()
    ents = get_entitlements(db)
    if ents.allows_engine(eng):
        return
    if eng in PRO_ENGINES:
        raise HTTPException(
            LICENSE_HTTP_STATUS,
            f"{eng.upper()} connections require DataMETL Pro. "
            "PostgreSQL is available on Community. Activate a license in Settings.",
        )
    raise HTTPException(400, f"Unsupported engine: {engine}")


def require_mel_approval_choice(db: Session, mode: str) -> None:
    """Community may only keep/use 'always'; Pro may pick any mode."""
    ents = get_entitlements(db)
    if ents.can_choose_mel_approval():
        return
    if mode == "always":
        return
    raise HTTPException(LICENSE_HTTP_STATUS, COMMUNITY_MEL_LIMIT)
