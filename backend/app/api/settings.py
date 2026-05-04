"""App-level settings + diagnostics surface.

Exposes non-secret config (log level, CORS origins, queue depth, worker tuning) so the UI
can render an at-a-glance Settings page. Secrets — the actual encryption key, full DB DSN
with password — are never returned. URLs are shown with credentials redacted.
"""
from __future__ import annotations

import re
from typing import Any

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter

from app.api.schemas_io import SettingsResponse
from app.config import settings as cfg
from app.jobs.worker import WorkerSettings

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
            return await pool.zcard("arq:queue")
        finally:
            await pool.close()
    except Exception:  # noqa: BLE001
        return 0


@router.get("", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    return SettingsResponse(
        version=_VERSION,
        log_level=cfg.log_level,
        encryption_key_set=bool(cfg.encryption_key),
        cors_origins=cfg.cors_origin_list,
        redis_url_redacted=_redact_url(cfg.redis_url),
        database_url_redacted=_redact_url(cfg.database_url),
        queue_depth=await _queue_depth(),
        worker_max_jobs=getattr(WorkerSettings, "max_jobs", 4),
        worker_job_timeout_seconds=getattr(WorkerSettings, "job_timeout", 1800),
    )
