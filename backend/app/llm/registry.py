"""Resolve Mel model ids to providers and list what the operator can pick from."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.config import settings
from app.llm.anthropic_provider import (
    ANTHROPIC_DEFAULT_MODEL,
    ANTHROPIC_MODELS,
    AnthropicProvider,
)
from app.llm.base import ChatProvider, ProviderError
from app.llm.ollama import (
    OllamaProvider,
    is_ollama_model,
    list_ollama_models,
    model_id,
    ollama_tag,
)
from app.settings_store import get_anthropic_key, get_ollama_base_url

log = logging.getLogger("datametl.llm")

# ChatSession.model is String(64); keep ids within it so saving a chat never fails.
MAX_MODEL_ID_LEN = 64


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: Literal["anthropic", "ollama"]
    # None = unknown (old Ollama server). Anthropic models all support tools.
    supports_tools: bool | None = True


def anthropic_models() -> list[ModelInfo]:
    return [ModelInfo(id=m, label=m, provider="anthropic") for m in ANTHROPIC_MODELS]


def effective_ollama_base_url(db: Session) -> str:
    """Stored setting wins; else the OLLAMA_BASE_URL env default; else '' (disabled)."""
    return get_ollama_base_url(db) or (settings.ollama_base_url or "").strip()


async def list_models(db: Session) -> tuple[list[ModelInfo], str]:
    """All selectable models and the default id.

    Anthropic models are always listed (the key may be added later). Ollama chat-capable
    models are listed live from the configured host; an unreachable host contributes nothing.
    """
    models = anthropic_models()
    base_url = effective_ollama_base_url(db)
    if base_url:
        try:
            local = await list_ollama_models(base_url)
        except ProviderError as e:
            log.warning("ollama model listing skipped: %s", e)
            local = []
        models.extend(
            ModelInfo(
                id=model_id(m.name),
                label=m.name,
                provider="ollama",
                supports_tools=m.supports_tools,
            )
            for m in local
            # Embedding-only models can't chat; ids must fit ChatSession.model.
            if m.can_chat and len(model_id(m.name)) <= MAX_MODEL_ID_LEN
        )
    default = default_model(models, anthropic_key_set=get_anthropic_key(db) is not None)
    return models, default


def default_model(models: list[ModelInfo], *, anthropic_key_set: bool) -> str:
    """Anthropic's default when a key exists; otherwise the first local model; else Anthropic."""
    if anthropic_key_set:
        return ANTHROPIC_DEFAULT_MODEL
    for m in models:
        if m.provider == "ollama":
            return m.id
    return ANTHROPIC_DEFAULT_MODEL


def provider_for(db: Session, model: str) -> tuple[ChatProvider, str]:
    """Return the provider for ``model`` plus the id to send it. Raises ProviderError."""
    if len(model) > MAX_MODEL_ID_LEN:
        raise ProviderError(f"Model id too long (max {MAX_MODEL_ID_LEN} chars).")
    if is_ollama_model(model):
        base_url = effective_ollama_base_url(db)
        if not base_url:
            raise ProviderError("Ollama is not configured. Set its URL in Settings.")
        if not ollama_tag(model):
            raise ProviderError("Ollama model name is empty.")
        return (
            OllamaProvider(
                base_url,
                timeout_s=float(settings.ollama_timeout_seconds),
                num_ctx=int(settings.ollama_num_ctx),
            ),
            model,
        )
    if model in ANTHROPIC_MODELS:
        key = get_anthropic_key(db)
        if not key:
            raise ProviderError("No Anthropic API key configured. Set one in Settings.")
        return AnthropicProvider(key), model
    raise ProviderError(f"Unknown model: {model}")
