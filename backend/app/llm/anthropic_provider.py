"""Anthropic Messages API provider (the original Mel backend)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam, ToolParam

from app.llm.base import Message, ProviderError, ToolCall, ToolSpec, TurnEnd

# Exact current model IDs (no date suffixes). Opus 4.8 is the default.
ANTHROPIC_MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
# A faster, cheaper default than Opus for tight single-shot tasks (describe a SQL script).
ANTHROPIC_FAST_MODEL = "claude-sonnet-4-6"

# Adaptive thinking + the `effort` knob are supported on Opus 4.6+ and Sonnet 4.6, but NOT on
# Haiku 4.5 (effort 400s there). Only attach those params for models that accept them.
THINKING_EFFORT_MODELS = {"claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6"}


def to_anthropic_messages(messages: list[Message]) -> list[MessageParam]:
    """Neutral conversation → Anthropic ``messages`` (tool calls/results as content blocks)."""
    out: list[MessageParam] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": str(m.get("content", ""))})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = str(m.get("content", "") or "")
            if text:
                blocks.append({"type": "text", "text": text})
            for c in m.get("tool_calls") or []:
                blocks.append(
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("input") or {}}
                )
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            out.append(cast(MessageParam, {"role": "assistant", "content": blocks}))
        elif role == "tool_results":
            results = [
                {
                    "type": "tool_result",
                    "tool_use_id": r["id"],
                    "content": r.get("content", ""),
                    "is_error": bool(r.get("is_error")),
                }
                for r in m.get("results") or []
            ]
            out.append(cast(MessageParam, {"role": "user", "content": results}))
        else:
            raise ProviderError(f"Unknown message role: {role!r}")
    return out


def to_anthropic_system(system: list[str]) -> list[TextBlockParam]:
    blocks: list[TextBlockParam] = []
    for i, text in enumerate(system):
        if i == 0:
            # Stable prefix → cacheable.
            blocks.append({"type": "text", "text": text, "cache_control": {"type": "ephemeral"}})
        else:
            blocks.append({"type": "text", "text": text})
    return blocks


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ProviderError("No Anthropic API key configured. Set one in Settings.")
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream_turn(
        self,
        *,
        model: str,
        system: list[str],
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str | TurnEnd]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": to_anthropic_system(system),
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = cast(list[ToolParam], tools)
        elif model in THINKING_EFFORT_MODELS:
            # Thinking only on plain chat: replaying thinking blocks through the tool loop is
            # not something the neutral conversation shape carries.
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": "medium"}
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text
                final = await stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise ProviderError(e.message) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Could not reach the Anthropic API: {e}") from e

        text_out = "".join(b.text for b in final.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input) if isinstance(b.input, dict) else {})
            for b in final.content
            if b.type == "tool_use"
        ]
        yield TurnEnd(text=text_out, tool_calls=calls, stop_reason=final.stop_reason or "end_turn")
