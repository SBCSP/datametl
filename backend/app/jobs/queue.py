"""Async helpers used by API routes to enqueue jobs and check status."""
from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from app.config import settings


async def get_pool() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


async def enqueue(function: str, *args: Any) -> str:
    pool = await get_pool()
    try:
        job = await pool.enqueue_job(function, *args)
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
            except Exception as e:  # noqa: BLE001 — arq raises whatever the function raised
                error = str(e)
        return {
            "id": job_id,
            "status": s.value,
            "function": info.function if info else None,
            "enqueue_time": info.enqueue_time.isoformat() if info and info.enqueue_time else None,
            "result": result,
            "error": error,
        }
    finally:
        await pool.close()
