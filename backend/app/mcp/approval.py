"""Mel tool approval: which tools need operator confirm, and Redis-backed proposal waiters.

Pending proposals live in Redis (keyed by proposal id) with a TTL so Approve/Deny works
across multiple uvicorn / API workers. The chat stream emits `tool_pending`, then
`wait_decision` polls Redis until another process POSTs approve/deny (or timeout).

Fail-closed: Redis is required. If Redis is unavailable, `register_proposal` /
`wait_decision` raise and `resolve_decision` returns False — tools never auto-run.
There is no in-process Future fallback: that would silently break multi-worker safety.
(Redis is already required for arq job queues.)
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from typing import Any, Protocol

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)

# Tools Mel may call against the active read-only MCP connection.
MEL_TOOLS = frozenset({"list_tables", "describe_table", "run_sql"})

# Settings values for mel_tool_approval.
APPROVAL_RUN_SQL_ONLY = "run_sql_only"  # default — SQL still needs a human click
APPROVAL_ALWAYS = "always"
APPROVAL_AUTO = "auto"
APPROVAL_MODES = frozenset({APPROVAL_RUN_SQL_ONLY, APPROVAL_ALWAYS, APPROVAL_AUTO})
DEFAULT_APPROVAL_MODE = APPROVAL_RUN_SQL_ONLY

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)

APPROVAL_TIMEOUT_S = 300.0  # 5 minutes — operator walked away
_KEY_PREFIX = "datametl:mel:approval:"
# Keep the key a bit past the waiter timeout so a late resolve still sees "pending"→deny cleanup.
_TTL_S = int(APPROVAL_TIMEOUT_S) + 60
_POLL_INTERVAL_S = 0.1

# Atomic: only transition pending → approve|deny (returns 1 if we won the race).
_RESOLVE_LUA = """
local cur = redis.call('GET', KEYS[1])
if cur == 'pending' then
  redis.call('SET', KEYS[1], ARGV[1], 'KEEPTTL')
  return 1
end
return 0
"""


class MelApprovalRedisUnavailable(RuntimeError):
    """Raised when Redis cannot store or wait on a Mel approval (fail closed)."""


class _AsyncRedisLike(Protocol):
    async def get(self, name: str) -> str | None: ...
    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool | None: ...
    async def delete(self, *names: str) -> int: ...
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str
    ) -> Any: ...
    async def scan(
        self, cursor: int = 0, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]: ...
    async def aclose(self) -> None: ...
    async def ping(self) -> bool: ...


_client: _AsyncRedisLike | None = None
_client_lock = asyncio.Lock()


def _key(proposal_id: uuid.UUID | str) -> str:
    return f"{_KEY_PREFIX}{proposal_id}"


def set_redis_client_for_tests(client: _AsyncRedisLike | None) -> None:
    """Inject a fake/async Redis (or reset to None) — tests only."""
    global _client
    _client = client


async def _get_client() -> _AsyncRedisLike:
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            _client = redis.from_url(settings.redis_url, decode_responses=True)
        return _client


async def close_redis_client() -> None:
    """Close the shared async Redis client (tests / shutdown)."""
    global _client
    async with _client_lock:
        if _client is not None:
            with contextlib.suppress(Exception):
                await _client.aclose()
            _client = None


def needs_approval(tool_name: str, mode: str) -> bool:
    """Whether this tool must wait for Approve/Deny under the given settings mode."""
    if mode == APPROVAL_AUTO:
        return False
    if mode == APPROVAL_ALWAYS:
        return tool_name in MEL_TOOLS
    # run_sql_only (default) — safer for the tool that actually runs operator SQL
    return tool_name == "run_sql"


def redact_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Copy tool args for audit storage, stripping secret-looking keys and truncating long strings."""
    if not args:
        return {}
    out: dict[str, Any] = {}
    for key, value in args.items():
        k = str(key)
        if _SECRET_KEY_RE.search(k):
            out[k] = "[redacted]"
        elif isinstance(value, dict):
            out[k] = redact_args(value)
        elif isinstance(value, str):
            out[k] = value if len(value) <= 4000 else value[:4000] + "…"
        else:
            out[k] = value
    return out


def args_summary(tool_name: str, args: dict[str, Any] | None) -> str:
    """Short one-line summary for the chat Approve/Deny card and activity feed."""
    args = args or {}
    if tool_name == "list_tables":
        return "list tables"
    if tool_name == "describe_table":
        schema = str(args.get("schema") or "")
        table = str(args.get("table") or "")
        return f"describe {schema}.{table}".strip(".")
    if tool_name == "run_sql":
        q = " ".join(str(args.get("query") or "").split())
        if not q:
            return "run_sql (empty)"
        return q if len(q) <= 140 else q[:140] + "…"
    try:
        raw = json.dumps(args, default=str)
    except Exception:
        raw = str(args)
    return raw if len(raw) <= 140 else raw[:140] + "…"


def outcome_summary(result_json: str, *, denied: bool = False, error: str | None = None) -> str:
    if denied:
        return "Denied by operator — not executed"
    if error:
        return f"Error: {error[:200]}"
    try:
        data = json.loads(result_json)
    except Exception:
        return (result_json or "")[:160]
    if isinstance(data, dict):
        if data.get("error"):
            return f"Error: {str(data['error'])[:200]}"
        if "tables" in data and "count" in data:
            return f"{data['count']} tables"
        if "columns" in data and "row_count" in data:
            n = data.get("row_count", 0)
            trunc = " (truncated)" if data.get("truncated") else ""
            return f"{n} row{'s' if n != 1 else ''}{trunc}"
        if "row_count" in data:
            n = data.get("row_count", 0)
            trunc = " (truncated)" if data.get("truncated") else ""
            return f"{n} row{'s' if n != 1 else ''}{trunc}"
    return "ok"


async def register_proposal(proposal_id: uuid.UUID | str) -> None:
    """Mark a proposal pending in Redis (call before emitting tool_pending).

    Replaces any stale pending/decided value for the same id. Raises
    MelApprovalRedisUnavailable if Redis cannot be reached (fail closed).
    """
    key = _key(proposal_id)
    try:
        client = await _get_client()
        await client.set(key, "pending", ex=_TTL_S)
    except (RedisError, OSError, TimeoutError) as e:
        logger.error("Mel approval register failed (Redis unavailable): %s", e)
        raise MelApprovalRedisUnavailable(
            "Redis unavailable — cannot register Mel tool approval (fail closed)."
        ) from e


async def wait_decision(proposal_id: uuid.UUID | str, timeout: float = APPROVAL_TIMEOUT_S) -> str:
    """Block until Approve/Deny (or timeout → deny). Cleans up the Redis key.

    Polls Redis so any worker that called resolve_decision can wake this waiter.
    Fail closed: Redis errors raise MelApprovalRedisUnavailable (caller must not
    execute the tool). Missing/expired keys are treated as deny.
    """
    key = _key(proposal_id)
    deadline = time.monotonic() + timeout
    try:
        client = await _get_client()
    except (RedisError, OSError, TimeoutError) as e:
        logger.error("Mel approval wait failed to connect Redis: %s", e)
        raise MelApprovalRedisUnavailable(
            "Redis unavailable — cannot wait for Mel tool approval (fail closed)."
        ) from e

    # Ensure a pending key exists (idempotent if register already ran).
    try:
        existing = await client.get(key)
        if existing is None:
            await client.set(key, "pending", ex=_TTL_S)
        elif existing in ("approve", "deny"):
            await client.delete(key)
            return existing
    except (RedisError, OSError, TimeoutError) as e:
        logger.error("Mel approval wait Redis error: %s", e)
        raise MelApprovalRedisUnavailable(
            "Redis unavailable — cannot wait for Mel tool approval (fail closed)."
        ) from e

    while True:
        try:
            val = await client.get(key)
        except (RedisError, OSError, TimeoutError) as e:
            logger.error("Mel approval wait Redis error: %s", e)
            raise MelApprovalRedisUnavailable(
                "Redis unavailable — cannot wait for Mel tool approval (fail closed)."
            ) from e

        if val in ("approve", "deny"):
            with contextlib.suppress(RedisError, OSError, TimeoutError):
                await client.delete(key)
            return val

        if val is None:
            # TTL expired or cleared elsewhere — fail closed
            return "deny"

        if time.monotonic() >= deadline:
            await resolve_decision(proposal_id, "deny")
            # Best-effort cleanup; resolve already set deny
            with contextlib.suppress(RedisError, OSError, TimeoutError):
                final = await client.get(key)
                if final in ("approve", "deny"):
                    await client.delete(key)
                    return final
            return "deny"

        await asyncio.sleep(_POLL_INTERVAL_S)


async def resolve_decision(proposal_id: uuid.UUID | str, decision: str) -> bool:
    """Called by the Approve/Deny API. Returns False if no pending proposal or Redis down."""
    if decision not in ("approve", "deny"):
        return False
    key = _key(proposal_id)
    try:
        client = await _get_client()
        changed = await client.eval(_RESOLVE_LUA, 1, key, decision)
        return int(changed or 0) == 1
    except (RedisError, OSError, TimeoutError) as e:
        logger.error("Mel approval resolve failed (Redis unavailable): %s", e)
        return False


async def clear_all_pending() -> None:
    """Test helper — delete every Mel approval key under the prefix."""
    try:
        client = await _get_client()
    except (RedisError, OSError, TimeoutError):
        return
    cursor = 0
    pattern = f"{_KEY_PREFIX}*"
    try:
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except (RedisError, OSError, TimeoutError, AttributeError):
        # Fake clients may only support delete of known keys; ignore.
        pass
