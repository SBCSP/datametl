"""App-level settings + diagnostics surface.

Exposes non-secret config (log level, CORS origins, queue depth, worker tuning) so the UI
can render an at-a-glance Settings page. Secrets — the actual encryption key, full DB DSN
with password — are never returned. URLs are shown with credentials redacted.
"""
from __future__ import annotations

import re

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    AnthropicKeyStatus,
    AnthropicKeyUpdate,
    MelToolApprovalStatus,
    MelToolApprovalUpdate,
    SettingsResponse,
)
from app.config import settings as cfg
from app.db import get_db
from app.jobs.worker import WorkerSettings
from app.settings_store import (
    get_mel_tool_approval,
    has_anthropic_key,
    set_anthropic_key,
    set_mel_tool_approval,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_VERSION = "0.2.6"  # Bump alongside meaningful releases. Surfaced in About panel.


def _redact_url(url: str) -> str:
    """Strip user:password from a URL while keeping the rest readable."""
    return re.sub(r"://[^@/]+@", "://***@", url)


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
        mel_tool_approval=get_mel_tool_approval(db),
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
    """How Mel DB tools are confirmed in chat: run_sql_only (default), always, or auto."""
    try:
        mode = set_mel_tool_approval(db, payload.mel_tool_approval)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return MelToolApprovalStatus(mel_tool_approval=mode)  # type: ignore[arg-type]
