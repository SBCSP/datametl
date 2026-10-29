"""Pluggable chat model providers for Mel (Anthropic API, local Ollama).

The chat endpoint speaks one provider-neutral conversation shape (see ``base.py``); each
provider converts it to its own wire format. Adding a provider means implementing
``ChatProvider`` and registering its model-id prefix in ``registry.py``.
"""
from app.llm.base import (
    ChatProvider,
    Message,
    ProviderError,
    ToolCall,
    ToolResult,
    ToolSpec,
    TurnEnd,
    assistant_message,
    tool_results_message,
    user_message,
)

__all__ = [
    "ChatProvider",
    "Message",
    "ProviderError",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "TurnEnd",
    "assistant_message",
    "tool_results_message",
    "user_message",
]
