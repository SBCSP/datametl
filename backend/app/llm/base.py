"""Provider-neutral chat types shared by the Anthropic and Ollama providers.

Conversation shape (a list of ``Message`` dicts):
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall-as-dict, ...]}
  {"role": "tool_results", "results": [ToolResult-as-dict, ...]}

Tool specs use the Anthropic shape ({name, description, input_schema}); providers that need
another shape (Ollama/OpenAI-style ``function.parameters``) convert on the way out.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

Message = dict[str, Any]
ToolSpec = dict[str, Any]


class ProviderError(Exception):
    """A user-presentable provider failure (bad config, HTTP error, unsupported feature)."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class TurnEnd:
    """Terminal event of one model turn: the full assistant text and any tool calls."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def user_message(content: str) -> Message:
    return {"role": "user", "content": content}


def assistant_message(end: TurnEnd) -> Message:
    return {
        "role": "assistant",
        "content": end.text,
        "tool_calls": [asdict(c) for c in end.tool_calls],
    }


def tool_results_message(results: list[ToolResult]) -> Message:
    return {
        "role": "tool_results",
        "results": [
            {
                "id": r.call.id,
                "name": r.call.name,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in results
        ],
    }


class ChatProvider(Protocol):
    """One streamed model turn. Yields text deltas, then exactly one ``TurnEnd``.

    ``system`` is a list of text blocks (first is the stable, cacheable prefix).
    ``tools`` None/empty → plain chat. Implementations raise ``ProviderError`` for anything
    the operator should see; other exceptions are treated as bugs by the caller.
    """

    name: str

    def stream_turn(
        self,
        *,
        model: str,
        system: list[str],
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str | TurnEnd]: ...
