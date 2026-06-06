"""Best-effort live job progress, stored in Redis keyed by job id.

The worker writes a small progress dict (e.g. introspection table counts) as it goes; the
`GET /api/jobs/{id}` status endpoint reads it back so the UI can show a live progress bar. Writes
use a synchronous redis client (they happen inside a worker thread, off the event loop) and are
wrapped so a Redis hiccup never breaks the actual job. Keys expire on their own.
"""
from __future__ import annotations

import json
import time
from typing import Any

import redis

from app.config import settings

_PREFIX = "datametl:progress:"
_TTL_SECONDS = 3600

_client: redis.Redis | None = None


def _sync_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url)
    return _client


def key(job_id: str) -> str:
    return f"{_PREFIX}{job_id}"


def set_progress(job_id: str, data: dict[str, Any]) -> None:
    """Upsert the progress snapshot for a job (best-effort)."""
    try:
        payload = json.dumps({**data, "updated_at": time.time()})
        _sync_client().set(key(job_id), payload, ex=_TTL_SECONDS)
    except Exception:  # never let progress reporting break a job
        pass


def parse(raw: bytes | str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except Exception:
        return None
