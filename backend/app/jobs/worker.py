"""arq worker entrypoint. Run with: `arq app.jobs.worker.WorkerSettings`."""
from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import settings
from app.jobs.tasks import introspect_connection, run_comparison, run_migration, run_verification

# arq workers run in their own process (separate from FastAPI's main.py), so configure
# the root logger here too. Without this, our `log.info(...)` calls in introspectors are
# swallowed at the default WARNING level.
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [introspect_connection, run_comparison, run_migration, run_verification]
    redis_settings = _redis_settings()
    keep_result = 3600  # seconds — UI polls for status
    max_jobs = 4
    # Default arq timeout is 5 min. Real RDS / Supabase introspections over the public
    # internet (~100ms latency × 4 round-trips per table × N tables) can legitimately run
    # longer. Bump to 30 min so we don't kill an in-flight job.
    job_timeout = 1800
