"""Async helpers used by API routes to enqueue jobs and check status."""
from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from app.config import settings
from app.jobs import progress as progress_mod

_UNSET: object = object()


async def get_pool() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


async def enqueue(function: str, *args: Any, tenant_id: Any = _UNSET) -> str:
    """Enqueue an arq job, appending ``tenant_id`` as the last positional arg.

    When ``tenant_id`` is omitted, uses the current request ContextVar (set by
    TenantBindingMiddleware). Explicit ``None`` means legacy/cutover fallback in the worker.
    """
    if tenant_id is _UNSET:
        from app.tenancy.context import get_tenant_context

        ctx = get_tenant_context()
        tenant_id = str(ctx.tenant_id) if ctx is not None else None
    job_args = (*args, tenant_id)
    pool = await get_pool()
    try:
        job = await pool.enqueue_job(function, *job_args)
        if job is None:
            raise RuntimeError("arq returned no job — Redis unavailable?")
        return job.job_id
    finally:
        await pool.close()


async def status(job_id: str) -> dict[str, Any]:
    pool = await get_pool()
    try:
        job = Job(job_id, redis=pool)
        info = await job.info()
        s: JobStatus = await job.status()
        result: Any = None
        error: str | None = None
        if s == JobStatus.complete:
            try:
                result = await job.result(timeout=0.1)
            except Exception as e:
                error = str(e)
        # Live progress snapshot (best-effort), written by the worker as it runs.
        progress = None
        try:
            progress = progress_mod.parse(await pool.get(progress_mod.key(job_id)))
        except Exception:
            progress = None
        return {
            "id": job_id,
            "status": s.value,
            "function": info.function if info else None,
            "enqueue_time": info.enqueue_time.isoformat() if info and info.enqueue_time else None,
            "result": result,
            "error": error,
            "progress": progress,
        }
    finally:
        await pool.close()
