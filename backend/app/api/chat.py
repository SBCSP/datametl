"""Streaming chat with Claude via the Anthropic API.

Phase 1: plain chat (no DB/tool use). This is a direct streaming endpoint, NOT an arq job —
it touches no user database, so the request handler streams tokens straight back to the
browser. The Anthropic key is read from the encrypted app-settings store.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlockParam
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    ChatMessageIn,
    ChatModelsResponse,
    ChatRequest,
    ChatSessionCreate,
    ChatSessionRead,
    ChatSessionSummary,
    ChatSessionUpdate,
)
from app.db import get_db
from app.models.chat_session import ChatSession
from app.settings_store import get_anthropic_key

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Exact current model IDs (no date suffixes). Opus 4.8 is the default.
CHAT_MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
DEFAULT_MODEL = "claude-opus-4-8"

# Adaptive thinking + the `effort` knob are supported on Opus 4.6+ and Sonnet 4.6, but NOT on
# Haiku 4.5 (effort 400s there). Only attach those params for models that accept them.
THINKING_EFFORT_MODELS = {"claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6"}

# Stable, no dynamic content (keeps the prompt cacheable once the prefix grows in later phases).
SYSTEM_PROMPT = """\
You are Mel, DataMETL's built-in database expert: a senior PostgreSQL DBA and data-migration \
engineer embedded in DataMETL, a local-first tool for migrating databases. Its primary use \
case is moving a Supabase project to vanilla PostgreSQL. Your user is an operator running real \
migrations against real data — be the calm, precise expert they'd want on call. If asked who \
you are, you're Mel; don't over-introduce yourself otherwise — just help.

## Your expertise
- PostgreSQL administration and internals: schema design, data types, indexes, constraints, \
sequences/identity, partitioning, vacuum/autovacuum, bloat, locks and MVCC, WAL, replication \
and replication slots, EXPLAIN/query planning, and performance tuning.
- Migration engineering: schema diffing, type mapping and lossy conversions, streaming COPY, \
batching, FK-dependency ordering, deferring/replicating constraints, sequence resync (setval), \
idempotent/repeatable loads, conflict modes (truncate vs append), verification (row counts, \
hashing, sequence parity), cutover and rollback planning, and minimizing downtime.
- Supabase specifics: the auth/storage/realtime schemas, RLS policies, gen_random_uuid() \
defaults, auth.uid()/auth.role() in views and policies, FKs to auth.users, and what does and \
doesn't carry over to vanilla Postgres.
- Managed-Postgres operations that bite migrations: RDS/Aurora storage, autoscaling and WAL/\
TransactionLogsDiskUsage, disk/IOPS limits, inactive replication slots, and backups.

## How to answer
- Lead with the recommendation or answer, then the supporting reasoning. Concise and practical \
— skip filler and over-explanation.
- Write SQL in PostgreSQL dialect inside fenced ```sql blocks; prefer standard, runnable statements.
- Flag risk explicitly: mark anything destructive or lock-taking, note when something needs a \
maintenance window or downtime, and prefer the safe, reversible path. Default to \
non-destructive suggestions unless the operator asks otherwise.
- When the answer depends on specifics you don't have, ask for them — DDL, the table's `\\d` \
output, the exact error text, row counts, the Postgres/Supabase version — rather than guessing. \
Concrete beats plausible.
- Right-size depth to the question: a quick lookup gets a short answer; a migration-design \
question gets the trade-offs plus a recommended approach.

## What you can and can't do right now
- You do NOT yet have direct access to the operator's databases. Reason from what they share \
plus your expertise, and ask for schema/DDL/errors when you need them.
- The operator can run **read-only** SQL against their connected databases from DataMETL's \
"SQL Scripts" page. When you suggest investigative queries (counts, sizes, catalog lookups), \
give read-only SQL they can paste and run there — don't assume you can execute anything yourself.
- DataMETL never writes to a migration's source database, and surfaces tables that exist only \
on the source as DDL preview for the operator to run themselves. Keep your advice consistent \
with that safety model.

Stay in the database / migration lane. If asked something unrelated, answer briefly and steer \
back toward their database work."""


@router.get("/models", response_model=ChatModelsResponse)
def list_models() -> ChatModelsResponse:
    return ChatModelsResponse(models=CHAT_MODELS, default=DEFAULT_MODEL)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    if payload.model not in CHAT_MODELS:
        raise HTTPException(400, f"Unknown model: {payload.model}")
    api_key = get_anthropic_key(db)
    if not api_key:
        raise HTTPException(400, "No Anthropic API key configured. Set one in Settings.")

    # Pull plain dict messages out now, while the request is in scope — the generator below
    # runs after this handler returns, so it must not touch `db`.
    messages: list[MessageParam] = [
        {"role": m.role, "content": m.content} for m in payload.messages
    ]
    model = payload.model

    system: list[TextBlockParam] = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    # Adaptive thinking + the `effort` knob only on models that support them (Haiku 4.5 400s on
    # effort), so branch rather than always passing them.
    use_thinking = model in THINKING_EFFORT_MODELS

    async def token_stream() -> AsyncIterator[str]:
        client = AsyncAnthropic(api_key=api_key)
        try:
            if use_thinking:
                stream_ctx = client.messages.stream(
                    model=model, max_tokens=8192, system=system, messages=messages,
                    thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                )
            else:
                stream_ctx = client.messages.stream(
                    model=model, max_tokens=8192, system=system, messages=messages,
                )
            async with stream_ctx as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APIStatusError as e:
            # Surface a safe message in-stream (status already 200 once streaming began).
            yield f"\n\n[error: {e.message}]"
        except Exception as e:  # never leak a traceback into the chat
            yield f"\n\n[error: {e}]"

    return StreamingResponse(token_stream(), media_type="text/plain; charset=utf-8")


# --- Persisted chat sessions ---

def _derive_title(messages: list[ChatMessageIn]) -> str:
    """Title a saved chat from its first user message; fall back to 'New chat'."""
    for m in messages:
        if m.role == "user" and m.content.strip():
            t = " ".join(m.content.split())[:60]
            return t or "New chat"
    return "New chat"


def _to_read(row: ChatSession) -> ChatSessionRead:
    return ChatSessionRead(
        id=row.id, title=row.title, model=row.model, messages=row.messages,
        created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions(db: Session = Depends(get_db)) -> list[ChatSessionSummary]:
    rows = db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc())).scalars()
    return [
        ChatSessionSummary(
            id=r.id, title=r.title, model=r.model, message_count=len(r.messages or []),
            created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(payload: ChatSessionCreate, db: Session = Depends(get_db)) -> ChatSessionRead:
    title = (payload.title or "").strip() or _derive_title(payload.messages)
    row = ChatSession(
        title=title,
        model=payload.model,
        messages=[m.model_dump() for m in payload.messages],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> ChatSessionRead:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    return _to_read(row)


@router.put("/sessions/{session_id}", response_model=ChatSessionRead)
def update_session(
    session_id: uuid.UUID, payload: ChatSessionUpdate, db: Session = Depends(get_db)
) -> ChatSessionRead:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    row.messages = [m.model_dump() for m in payload.messages]
    if payload.model:
        row.model = payload.model
    if payload.title and payload.title.strip():
        row.title = payload.title.strip()
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    db.delete(row)
    db.commit()
