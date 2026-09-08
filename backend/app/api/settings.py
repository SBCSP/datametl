"""App-level settings + diagnostics surface.

Exposes non-secret config (log level, CORS origins, queue depth, worker tuning) so the UI
can render an at-a-glance Settings page. Secrets — the actual encryption key, full DB DSN
with password, Anthropic key, license token — are never returned. URLs are shown with
credentials redacted.
"""
from __future__ import annotations

import re

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    AnthropicKeyStatus,
    AnthropicKeyUpdate,
    LicenseActivateRequest,
    LicenseActivateResponse,
    LicenseStatus,
    MelToolApprovalStatus,
    MelToolApprovalUpdate,
    SettingsResponse,
)
from app.config import settings as cfg
from app.db import get_db
from app.jobs.worker import WorkerSettings
from app.license.entitlements import COMMUNITY_MEL_LIMIT, get_entitlements
from app.license.gates import require_mel_approval_choice
from app.license.token import LicenseError, verify_license
from app.settings_store import (
    clear_license_key,
    get_mel_tool_approval,
    has_anthropic_key,
    has_license_key,
    set_anthropic_key,
    set_license_key,
    set_mel_tool_approval,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_VERSION = "0.2.6"  # Bump alongside meaningful releases. Surfaced in About panel.


def _redact_url(url: str) -> str:
    """Strip user:password from a URL while keeping the rest readable."""
    return re.sub(r"://[^@/]+@", "://***@", url)


def _license_status(db: Session) -> LicenseStatus:
    ents = get_entitlements(db)
    info = ents.info
    return LicenseStatus(
        tier=info.tier.value,  # type: ignore[arg-type]
        active=info.active,
        source=info.source,  # type: ignore[arg-type]
        issued_at=info.issued_at,
        expires_at=info.expires_at,
        email=info.email,
        seat_id=info.seat_id,
        instance_id=info.instance_id,
        message=info.message,
        community_mel_limit=COMMUNITY_MEL_LIMIT,
        can_use_mysql_mssql=ents.is_pro,
        can_choose_mel_approval=ents.can_choose_mel_approval(),
        allows_external_mcp=ents.allows_external_mcp(),
        license_key_set=has_license_key(db),
    )


async def _queue_depth() -> int:
    """Best-effort queue depth — counts pending arq jobs in the default queue.

    arq stores queued jobs in a sorted-set keyed `arq:queue:{queue_name}`. A ZCARD lookup
    tells us how many are pending. Connection failures return 0 rather than raise so the
    settings page still renders if Redis blips.
    """
    try:
        pool = await create_pool(RedisSettings.from_dsn(cfg.redis_url))
        try:
            return int(await pool.zcard("arq:queue"))
        finally:
            await pool.close()
    except Exception:
        return 0


@router.get("", response_model=SettingsResponse)
async def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    ents = get_entitlements(db)
    stored_approval = get_mel_tool_approval(db)
    return SettingsResponse(
        version=_VERSION,
        log_level=cfg.log_level,
        encryption_key_set=bool(cfg.encryption_key),
        anthropic_api_key_set=has_anthropic_key(db),
        cors_origins=cfg.cors_origin_list,
        redis_url_redacted=_redact_url(cfg.redis_url),
        database_url_redacted=_redact_url(cfg.database_url),
        queue_depth=await _queue_depth(),
        worker_max_jobs=getattr(WorkerSettings, "max_jobs", 4),
        worker_job_timeout_seconds=getattr(WorkerSettings, "job_timeout", 1800),
        auth_enabled=cfg.auth_enabled,
        auth_username=cfg.auth_username,
        auth_token_ttl_hours=cfg.auth_token_ttl_hours,
        mel_tool_approval=ents.effective_mel_tool_approval(stored_approval),
        license=_license_status(db),
    )


@router.put("/anthropic-key", response_model=AnthropicKeyStatus)
def update_anthropic_key(
    payload: AnthropicKeyUpdate, db: Session = Depends(get_db)
) -> AnthropicKeyStatus:
    """Store (or clear, when blank) the Anthropic API key. Write-only — never returned."""
    set_anthropic_key(db, payload.api_key)
    return AnthropicKeyStatus(anthropic_api_key_set=has_anthropic_key(db))


@router.put("/mel-tool-approval", response_model=MelToolApprovalStatus)
def update_mel_tool_approval(
    payload: MelToolApprovalUpdate, db: Session = Depends(get_db)
) -> MelToolApprovalStatus:
    """How Mel DB tools are confirmed in chat: run_sql_only (default), always, or auto.

    Community tier forces ``always`` — changing away requires Pro.
    """
    require_mel_approval_choice(db, payload.mel_tool_approval)
    try:
        mode = set_mel_tool_approval(db, payload.mel_tool_approval)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ents = get_entitlements(db)
    return MelToolApprovalStatus(
        mel_tool_approval=ents.effective_mel_tool_approval(mode)  # type: ignore[arg-type]
    )


@router.get("/license", response_model=LicenseStatus)
def get_license(db: Session = Depends(get_db)) -> LicenseStatus:
    return _license_status(db)


@router.post("/license", response_model=LicenseActivateResponse)
def activate_license(
    payload: LicenseActivateRequest, db: Session = Depends(get_db)
) -> LicenseActivateResponse:
    """Validate + persist a signed license key (Fernet-encrypted in app_settings)."""
    try:
        verify_license(payload.license_key)
    except LicenseError as e:
        raise HTTPException(400, str(e)) from e
    set_license_key(db, payload.license_key)
    return LicenseActivateResponse(license=_license_status(db))


@router.delete("/license", response_model=LicenseStatus)
def deactivate_license(db: Session = Depends(get_db)) -> LicenseStatus:
    """Remove the stored license key (returns to Community unless DEV_BYPASS)."""
    clear_license_key(db)
    return _license_status(db)
