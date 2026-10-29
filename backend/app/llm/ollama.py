"""Ollama provider — local models over the Ollama HTTP API (``/api/chat``, ``/api/tags``).

Nothing leaves the machine the Ollama server runs on. Tool calling uses Ollama's
OpenAI-style ``tools`` / ``message.tool_calls``; models without tool support fail with a clear
``ProviderError`` instead of a stack trace.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.llm.base import Message, ProviderError, ToolCall, ToolSpec, TurnEnd

MODEL_PREFIX = "ollama/"
DEFAULT_TIMEOUT_S = 300.0  # local models can be slow to first token on cold start
DEFAULT_NUM_CTX = 16384  # Mel's system prompt alone is ~1.5k tokens; Ollama's 4k default truncates
TAGS_TIMEOUT_S = 5.0


def normalize_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        raise ProviderError("Ollama URL must start with http:// or https://")
    return u


def model_id(name: str) -> str:
    """Ollama tag → Mel model id (``ollama/<tag>``)."""
    return f"{MODEL_PREFIX}{name}"


def is_ollama_model(model: str) -> bool:
    return model.startswith(MODEL_PREFIX)


def ollama_tag(model: str) -> str:
    """Mel model id → Ollama tag. Raises for ids that are not Ollama models."""
    if not is_ollama_model(model):
        raise ProviderError(f"Not an Ollama model: {model}")
    return model[len(MODEL_PREFIX) :]


def to_ollama_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """Anthropic {name, description, input_schema} → Ollama/OpenAI function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def to_ollama_messages(system: list[str], messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sys_text = "\n\n".join(s for s in system if s)
    if sys_text:
        out.append({"role": "system", "content": sys_text})
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": str(m.get("content", ""))})
        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": str(m.get("content", "") or "")}
            calls = m.get("tool_calls") or []
            if calls:
                msg["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": c.get("input") or {}}}
                    for c in calls
                ]
            out.append(msg)
        elif role == "tool_results":
            for r in m.get("results") or []:
                out.append({"role": "tool", "tool_name": r["name"], "content": str(r.get("content", ""))})
        else:
            raise ProviderError(f"Unknown message role: {role!r}")
    return out


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass(frozen=True)
class OllamaModel:
    name: str
    # None = server too old to report capabilities (pre-0.6); we fall back to a name heuristic.
    capabilities: tuple[str, ...] | None = None

    @property
    def can_chat(self) -> bool:
        if self.capabilities is None:
            return "embed" not in self.name.lower()
        return "completion" in self.capabilities

    @property
    def supports_tools(self) -> bool | None:
        return None if self.capabilities is None else ("tools" in self.capabilities)


async def _show_capabilities(
    client: httpx.AsyncClient, url: str, name: str
) -> tuple[str, ...] | None:
    try:
        resp = await client.post(f"{url}/api/show", json={"model": name})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    caps = data.get("capabilities") if isinstance(data, dict) else None
    if not isinstance(caps, list):
        return None
    return tuple(str(c) for c in caps)


async def list_ollama_models(
    base_url: str, *, timeout_s: float = TAGS_TIMEOUT_S
) -> list[OllamaModel]:
    """Models Ollama reports (``/api/tags``) with their ``/api/show`` capabilities.

    Raises ProviderError when the host is unreachable. Capability lookups that fail leave
    ``capabilities=None`` so an old server still lists its models.
    """
    url = normalize_base_url(base_url)
    if not url:
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(f"{url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models") if isinstance(data, dict) else None
            names = sorted(
                {str(m["name"]) for m in (models or []) if isinstance(m, dict) and m.get("name")}
            )
            caps = await asyncio.gather(*(_show_capabilities(client, url, n) for n in names))
    except httpx.HTTPStatusError as e:
        raise ProviderError(f"Ollama returned HTTP {e.response.status_code} from /api/tags") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach Ollama at {url}: {e.__class__.__name__}") from e
    except ValueError as e:
        raise ProviderError("Ollama /api/tags returned invalid JSON") from e
    return [OllamaModel(name=n, capabilities=c) for n, c in zip(names, caps, strict=True)]


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        num_ctx: int = DEFAULT_NUM_CTX,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        if not self.base_url:
            raise ProviderError("Ollama is not configured. Set its URL in Settings.")
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self._client = client  # injectable for tests

    def _make_client(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_s, connect=10.0)
        )

    async def stream_turn(
        self,
        *,
        model: str,
        system: list[str],
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str | TurnEnd]:
        payload: dict[str, Any] = {
            "model": ollama_tag(model),
            "messages": to_ollama_messages(system, messages),
            "stream": True,
            # Reasoning models (qwen3, deepseek-r1, …) are much slower with thinking on; Mel's
            # answers don't need it. Older servers 400 on the field — we retry without it.
            "think": False,
            "options": {"num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = to_ollama_tools(tools)

        client = self._make_client()
        owns_client = self._client is None
        try:
            async for item in self._stream(client, payload):
                yield item
        finally:
            if owns_client:
                await client.aclose()

    async def _stream(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> AsyncIterator[str | TurnEnd]:
        url = f"{self.base_url}/api/chat"
        for attempt in range(2):
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")
                        lowered = body.lower()
                        if attempt == 0 and resp.status_code == 400 and "think" in lowered:
                            payload.pop("think", None)
                            continue
                        raise ProviderError(_friendly_http_error(resp.status_code, body, payload["model"]))
                    text_parts: list[str] = []
                    calls: list[ToolCall] = []
                    done_reason = "end_turn"
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("error"):
                            raise ProviderError(f"Ollama: {data['error']}")
                        msg = data.get("message") or {}
                        delta = msg.get("content") or ""
                        if delta:
                            text_parts.append(delta)
                            yield delta
                        for tc in msg.get("tool_calls") or []:
                            fn = tc.get("function") or {}
                            calls.append(
                                ToolCall(
                                    id=str(tc.get("id") or uuid.uuid4()),
                                    name=str(fn.get("name", "")),
                                    input=_parse_arguments(fn.get("arguments")),
                                )
                            )
                        if data.get("done"):
                            done_reason = str(data.get("done_reason") or "stop")
                            break
                    yield TurnEnd(
                        text="".join(text_parts),
                        tool_calls=calls,
                        stop_reason="tool_use" if calls else done_reason,
                    )
                    return
            except httpx.HTTPError as e:
                raise ProviderError(
                    f"Could not reach Ollama at {self.base_url}: {e.__class__.__name__}"
                ) from e
        raise ProviderError("Ollama request failed after retry.")


def _friendly_http_error(status: int, body: str, model: str) -> str:
    lowered = body.lower()
    if "does not support tools" in lowered:
        return (
            f"Ollama model '{model}' does not support tool calling. Deactivate the live MCP "
            "connection or pick a tool-capable model (e.g. qwen3, llama3.1, mistral)."
        )
    if status == 404 or "not found" in lowered:
        return f"Ollama model '{model}' is not installed. Run `ollama pull {model}`."
    detail = body.strip()
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("error"):
            detail = str(parsed["error"])
    except json.JSONDecodeError:
        pass
    return f"Ollama returned HTTP {status}: {detail[:300]}"
