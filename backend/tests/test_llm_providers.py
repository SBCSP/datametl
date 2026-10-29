"""Mel model providers: Ollama wire conversion + streaming, Anthropic conversion, registry."""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.llm import registry
from app.llm.anthropic_provider import ANTHROPIC_MODELS, to_anthropic_messages, to_anthropic_system
from app.llm.base import ProviderError, ToolCall, ToolResult, TurnEnd, assistant_message, tool_results_message
from app.llm.ollama import (
    OllamaModel,
    OllamaProvider,
    is_ollama_model,
    list_ollama_models,
    model_id,
    normalize_base_url,
    ollama_tag,
    to_ollama_messages,
    to_ollama_tools,
)

TOOLS = [
    {
        "name": "describe_table",
        "description": "Get the columns of one table.",
        "input_schema": {
            "type": "object",
            "properties": {"schema": {"type": "string"}, "table": {"type": "string"}},
            "required": ["schema", "table"],
            "additionalProperties": False,
        },
    }
]


# --- ids / urls ---


def test_model_id_roundtrip() -> None:
    assert model_id("qwen3.5:9b") == "ollama/qwen3.5:9b"
    assert is_ollama_model("ollama/qwen3.5:9b")
    assert not is_ollama_model("claude-opus-4-8")
    assert ollama_tag("ollama/qwen3.5:9b") == "qwen3.5:9b"
    with pytest.raises(ProviderError):
        ollama_tag("claude-opus-4-8")


def test_normalize_base_url() -> None:
    assert normalize_base_url(" http://host.docker.internal:11434/ ") == "http://host.docker.internal:11434"
    assert normalize_base_url("") == ""
    with pytest.raises(ProviderError):
        normalize_base_url("host.docker.internal:11434")


# --- conversion ---


def test_to_ollama_tools_uses_function_shape() -> None:
    out = to_ollama_tools(TOOLS)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "describe_table"
    assert out[0]["function"]["parameters"]["required"] == ["schema", "table"]


def _conversation() -> list[dict[str, Any]]:
    call = ToolCall(id="tc1", name="describe_table", input={"schema": "public", "table": "posts"})
    end = TurnEnd(text="Let me look.", tool_calls=[call], stop_reason="tool_use")
    return [
        {"role": "user", "content": "describe posts"},
        assistant_message(end),
        tool_results_message([ToolResult(call=call, content='{"columns": []}', is_error=False)]),
    ]


def test_to_ollama_messages_flattens_system_and_tool_results() -> None:
    out = to_ollama_messages(["SYS", "NOTE"], _conversation())
    assert out[0] == {"role": "system", "content": "SYS\n\nNOTE"}
    assert out[1] == {"role": "user", "content": "describe posts"}
    assert out[2]["role"] == "assistant"
    assert out[2]["tool_calls"][0]["function"] == {
        "name": "describe_table",
        "arguments": {"schema": "public", "table": "posts"},
    }
    assert out[3] == {"role": "tool", "tool_name": "describe_table", "content": '{"columns": []}'}


def test_to_anthropic_messages_uses_content_blocks() -> None:
    out = to_anthropic_messages(_conversation())
    assert out[0] == {"role": "user", "content": "describe posts"}
    blocks = out[1]["content"]
    assert blocks[0] == {"type": "text", "text": "Let me look."}
    assert blocks[1]["type"] == "tool_use" and blocks[1]["id"] == "tc1"
    results = out[2]["content"]
    assert results[0]["type"] == "tool_result" and results[0]["tool_use_id"] == "tc1"
    sys_blocks = to_anthropic_system(["SYS", "NOTE"])
    assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in sys_blocks[1]


# --- ollama streaming (mock transport) ---


def _ndjson(*objs: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


def _provider(handler) -> OllamaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider("http://ollama.test", client=client)


async def test_stream_turn_yields_text_then_turn_end() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
            ),
        )

    items = [
        i
        async for i in _provider(handler).stream_turn(
            model="ollama/qwen3.5:4b", system=["SYS"], messages=[{"role": "user", "content": "hi"}]
        )
    ]
    assert items[:2] == ["Hel", "lo"]
    end = items[-1]
    assert isinstance(end, TurnEnd) and end.text == "Hello" and not end.wants_tools
    assert seen["payload"]["model"] == "qwen3.5:4b"
    assert seen["payload"]["think"] is False
    assert seen["payload"]["options"]["num_ctx"] == 16384
    assert "tools" not in seen["payload"]


async def test_stream_turn_collects_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"][0]["function"]["name"] == "describe_table"
        return httpx.Response(
            200,
            content=_ndjson(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "describe_table", "arguments": {"schema": "public", "table": "posts"}}}
                        ],
                    },
                    "done": False,
                },
                {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
            ),
        )

    items = [
        i
        async for i in _provider(handler).stream_turn(
            model="ollama/qwen3.5:4b",
            system=["SYS"],
            messages=[{"role": "user", "content": "describe posts"}],
            tools=TOOLS,
        )
    ]
    end = items[-1]
    assert isinstance(end, TurnEnd) and end.wants_tools and end.stop_reason == "tool_use"
    assert end.tool_calls[0].name == "describe_table"
    assert end.tool_calls[0].input == {"schema": "public", "table": "posts"}
    assert end.tool_calls[0].id  # generated when Ollama gives none


async def test_stream_turn_retries_without_think_on_400() -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if "think" in payload:
            return httpx.Response(400, json={"error": 'json: unknown field "think"'})
        return httpx.Response(
            200,
            content=_ndjson({"message": {"role": "assistant", "content": "ok"}, "done": True}),
        )

    items = [
        i
        async for i in _provider(handler).stream_turn(
            model="ollama/llama3", system=["SYS"], messages=[{"role": "user", "content": "hi"}]
        )
    ]
    assert len(calls) == 2 and "think" not in calls[1]
    assert items[0] == "ok"


async def test_stream_turn_explains_missing_tool_support() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "registry.ollama.ai/library/gemma does not support tools"})

    with pytest.raises(ProviderError, match="does not support tool calling"):
        async for _ in _provider(handler).stream_turn(
            model="ollama/gemma", system=["SYS"], messages=[{"role": "user", "content": "hi"}], tools=TOOLS
        ):
            pass


async def test_stream_turn_explains_missing_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": 'model "nope" not found, try pulling it first'})

    with pytest.raises(ProviderError, match="ollama pull nope"):
        async for _ in _provider(handler).stream_turn(
            model="ollama/nope", system=["SYS"], messages=[{"role": "user", "content": "hi"}]
        ):
            pass


async def test_list_ollama_models_sorted_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = {
        "qwen3.5:9b": ["completion", "tools", "thinking"],
        "llama3:8b": ["completion"],
        "nomic-embed-text:latest": ["embedding"],
    }

    def ok(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in caps]})
        assert request.url.path == "/api/show"
        name = json.loads(request.content)["model"]
        if name == "llama3:8b":
            return httpx.Response(200, json={"license": "…"})  # old server: no capabilities
        return httpx.Response(200, json={"capabilities": caps[name]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(ok), **kw)
    )
    models = await list_ollama_models("http://ollama.test")
    assert [m.name for m in models] == ["llama3:8b", "nomic-embed-text:latest", "qwen3.5:9b"]
    by_name = {m.name: m for m in models}
    assert by_name["qwen3.5:9b"].can_chat and by_name["qwen3.5:9b"].supports_tools is True
    assert not by_name["nomic-embed-text:latest"].can_chat
    # Unknown capabilities → name heuristic, tools unknown.
    assert by_name["llama3:8b"].can_chat and by_name["llama3:8b"].supports_tools is None

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(down), **kw)
    )
    with pytest.raises(ProviderError, match="Could not reach Ollama"):
        await list_ollama_models("http://ollama.test")


# --- registry ---


def test_default_model_prefers_anthropic_when_key_else_first_local() -> None:
    models = [
        *registry.anthropic_models(),
        registry.ModelInfo(id="ollama/qwen3.5:9b", label="qwen3.5:9b", provider="ollama"),
    ]
    assert registry.default_model(models, anthropic_key_set=True) == "claude-opus-4-8"
    assert registry.default_model(models, anthropic_key_set=False) == "ollama/qwen3.5:9b"
    assert registry.default_model(registry.anthropic_models(), anthropic_key_set=False) == "claude-opus-4-8"


def test_provider_for_resolves_by_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    monkeypatch.setattr(registry, "get_anthropic_key", lambda _db: None)
    monkeypatch.setattr(registry, "effective_ollama_base_url", lambda _db: "")
    with pytest.raises(ProviderError, match="No Anthropic API key"):
        registry.provider_for(db, ANTHROPIC_MODELS[0])
    with pytest.raises(ProviderError, match="Ollama is not configured"):
        registry.provider_for(db, "ollama/qwen3.5:9b")
    with pytest.raises(ProviderError, match="Unknown model"):
        registry.provider_for(db, "gpt-9")
    with pytest.raises(ProviderError, match="too long"):
        registry.provider_for(db, "ollama/" + "x" * 80)

    monkeypatch.setattr(registry, "effective_ollama_base_url", lambda _db: "http://ollama.test")
    provider, model = registry.provider_for(db, "ollama/qwen3.5:9b")
    assert provider.name == "ollama" and model == "ollama/qwen3.5:9b"

    monkeypatch.setattr(registry, "get_anthropic_key", lambda _db: "sk-ant-test")
    provider, model = registry.provider_for(db, ANTHROPIC_MODELS[0])
    assert provider.name == "anthropic" and model == ANTHROPIC_MODELS[0]


async def test_list_models_skips_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    monkeypatch.setattr(registry, "get_anthropic_key", lambda _db: None)
    monkeypatch.setattr(registry, "effective_ollama_base_url", lambda _db: "http://ollama.test")

    async def boom(_url: str) -> list[str]:
        raise ProviderError("Could not reach Ollama")

    monkeypatch.setattr(registry, "list_ollama_models", boom)
    infos, default = await registry.list_models(db)
    assert [m.id for m in infos] == ANTHROPIC_MODELS
    assert default == "claude-opus-4-8"

    async def tags(_url: str) -> list[OllamaModel]:
        return [
            OllamaModel("nomic-embed-text:latest", ("embedding",)),
            OllamaModel("qwen3.5:9b", ("completion", "tools")),
            OllamaModel("gemma3:4b", ("completion",)),
        ]

    monkeypatch.setattr(registry, "list_ollama_models", tags)
    infos, default = await registry.list_models(db)
    local = [m for m in infos if m.provider == "ollama"]
    # Embedding-only model excluded; tool support carried through.
    assert [m.id for m in local] == ["ollama/qwen3.5:9b", "ollama/gemma3:4b"]
    assert local[0].supports_tools is True and local[1].supports_tools is False
    assert default == "ollama/qwen3.5:9b"
