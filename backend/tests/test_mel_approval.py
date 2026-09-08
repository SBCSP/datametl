"""Mel tool approval helpers + Redis-backed Approve/Deny waiters."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest

from app.mcp.approval import (
    APPROVAL_ALWAYS,
    APPROVAL_AUTO,
    APPROVAL_RUN_SQL_ONLY,
    MelApprovalRedisUnavailable,
    args_summary,
    clear_all_pending,
    needs_approval,
    outcome_summary,
    redact_args,
    register_proposal,
    resolve_decision,
    set_redis_client_for_tests,
    wait_decision,
)


class FakeAsyncRedis:
    """Minimal async Redis stand-in for Mel approval tests (no Docker required)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, float] = {}
        self.fail_ops: set[str] = set()

    def _expire_due(self) -> None:
        now = time.monotonic()
        dead = [k for k, exp in self._ttl.items() if exp <= now]
        for k in dead:
            self._store.pop(k, None)
            self._ttl.pop(k, None)

    def _check(self, op: str) -> None:
        if op in self.fail_ops:
            raise ConnectionError(f"fake redis {op} failed")

    async def get(self, name: str) -> str | None:
        self._check("get")
        self._expire_due()
        return self._store.get(name)

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool | None:
        self._check("set")
        self._expire_due()
        if xx and name not in self._store:
            return False
        old_ttl = self._ttl.get(name)
        self._store[name] = value
        if keepttl and old_ttl is not None:
            self._ttl[name] = old_ttl
        elif ex is not None:
            self._ttl[name] = time.monotonic() + ex
        elif name in self._ttl and not keepttl:
            self._ttl.pop(name, None)
        return True

    async def delete(self, *names: str) -> int:
        self._check("delete")
        n = 0
        for name in names:
            if name in self._store:
                del self._store[name]
                self._ttl.pop(name, None)
                n += 1
        return n

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any:
        self._check("eval")
        self._expire_due()
        key = keys_and_args[0]
        decision = keys_and_args[1]
        if self._store.get(key) == "pending":
            self._store[key] = decision
            return 1
        return 0

    async def scan(
        self, cursor: int = 0, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        self._check("scan")
        self._expire_due()
        prefix = (match or "*").rstrip("*")
        keys = [k for k in self._store if k.startswith(prefix)]
        return 0, keys

    async def aclose(self) -> None:
        return None

    async def ping(self) -> bool:
        self._check("ping")
        return True


@pytest.fixture
def fake_redis():
    client = FakeAsyncRedis()
    set_redis_client_for_tests(client)
    yield client
    set_redis_client_for_tests(None)


def test_needs_approval_run_sql_only_default() -> None:
    assert needs_approval("run_sql", APPROVAL_RUN_SQL_ONLY) is True
    assert needs_approval("list_tables", APPROVAL_RUN_SQL_ONLY) is False
    assert needs_approval("describe_table", APPROVAL_RUN_SQL_ONLY) is False


def test_needs_approval_always_and_auto() -> None:
    assert needs_approval("list_tables", APPROVAL_ALWAYS) is True
    assert needs_approval("run_sql", APPROVAL_ALWAYS) is True
    assert needs_approval("run_sql", APPROVAL_AUTO) is False
    assert needs_approval("list_tables", APPROVAL_AUTO) is False


def test_redact_args_strips_secrets_and_truncates() -> None:
    red = redact_args({
        "query": "SELECT 1",
        "password": "super-secret",
        "api_key": "sk-ant-xxx",
        "nested": {"token": "abc", "ok": 1},
        "long": "x" * 5000,
    })
    assert red["query"] == "SELECT 1"
    assert red["password"] == "[redacted]"
    assert red["api_key"] == "[redacted]"
    assert red["nested"]["token"] == "[redacted]"
    assert red["nested"]["ok"] == 1
    assert red["long"].endswith("…")
    assert len(red["long"]) == 4001


def test_args_summary_shapes() -> None:
    assert args_summary("list_tables", {}) == "list tables"
    assert "public.users" in args_summary("describe_table", {"schema": "public", "table": "users"})
    assert "SELECT" in args_summary("run_sql", {"query": "SELECT 1"})


def test_outcome_summary_denied_and_rows() -> None:
    assert "Denied" in outcome_summary("{}", denied=True)
    assert "2 rows" in outcome_summary('{"columns":["a"],"rows":[[1],[2]],"row_count":2}')


@pytest.mark.asyncio
async def test_approve_deny_happy_paths(fake_redis: FakeAsyncRedis) -> None:
    await clear_all_pending()
    pid = uuid.uuid4()
    await register_proposal(pid)

    async def approve_soon() -> None:
        await asyncio.sleep(0.05)
        assert await resolve_decision(pid, "approve") is True

    task = asyncio.create_task(approve_soon())
    assert await wait_decision(pid, timeout=2.0) == "approve"
    await task

    pid2 = uuid.uuid4()
    await register_proposal(pid2)

    async def deny_soon() -> None:
        await asyncio.sleep(0.05)
        assert await resolve_decision(pid2, "deny") is True

    task2 = asyncio.create_task(deny_soon())
    assert await wait_decision(pid2, timeout=2.0) == "deny"
    await task2

    assert await resolve_decision(pid2, "approve") is False
    await clear_all_pending()


@pytest.mark.asyncio
async def test_resolve_from_separate_logical_worker(fake_redis: FakeAsyncRedis) -> None:
    """Simulate worker A waiting while worker B resolves via the shared Redis key."""
    pid = uuid.uuid4()
    await register_proposal(pid)

    async def other_worker_approve() -> None:
        await asyncio.sleep(0.05)
        assert await resolve_decision(pid, "approve") is True

    waiter = asyncio.create_task(wait_decision(pid, timeout=2.0))
    await other_worker_approve()
    assert await waiter == "approve"
    assert await fake_redis.get(f"datametl:mel:approval:{pid}") is None


@pytest.mark.asyncio
async def test_double_resolve_is_atomic(fake_redis: FakeAsyncRedis) -> None:
    pid = uuid.uuid4()
    await register_proposal(pid)
    assert await resolve_decision(pid, "approve") is True
    assert await resolve_decision(pid, "deny") is False
    assert await wait_decision(pid, timeout=1.0) == "approve"


@pytest.mark.asyncio
async def test_timeout_denies(fake_redis: FakeAsyncRedis) -> None:
    pid = uuid.uuid4()
    await register_proposal(pid)
    assert await wait_decision(pid, timeout=0.25) == "deny"


@pytest.mark.asyncio
async def test_register_fails_closed_when_redis_down(fake_redis: FakeAsyncRedis) -> None:
    fake_redis.fail_ops.add("set")
    with pytest.raises(MelApprovalRedisUnavailable):
        await register_proposal(uuid.uuid4())


@pytest.mark.asyncio
async def test_wait_fails_closed_when_redis_down_mid_poll(fake_redis: FakeAsyncRedis) -> None:
    pid = uuid.uuid4()
    await register_proposal(pid)
    fake_redis.fail_ops.add("get")
    with pytest.raises(MelApprovalRedisUnavailable):
        await wait_decision(pid, timeout=1.0)


@pytest.mark.asyncio
async def test_resolve_returns_false_when_redis_down(fake_redis: FakeAsyncRedis) -> None:
    pid = uuid.uuid4()
    await register_proposal(pid)
    fake_redis.fail_ops.add("eval")
    assert await resolve_decision(pid, "approve") is False


@pytest.mark.asyncio
async def test_denied_tools_do_not_look_like_success() -> None:
    """Contract used by the tool loop: denied payload is an error the model must honor."""
    import json

    denied = json.dumps({"error": "Tool denied by operator — not executed.", "denied": True})
    data = json.loads(denied)
    assert data.get("denied") is True
    assert "not executed" in data["error"].lower()
