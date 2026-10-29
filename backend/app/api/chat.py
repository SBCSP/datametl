"""Streaming chat for Mel over a pluggable model provider (Anthropic API or local Ollama).

Mel streams NDJSON events (token / tool_pending / tool_result / error / done). When a live
MCP connection is active, Mel may call read-only DB tools; depending on settings, run_sql
(and optionally all tools) pause for Approve/Deny in the chat UI before executing.
Approve/Deny waiters are Redis-backed so any API worker can resolve a pending proposal.
Tool cards are also persisted on the chat session (`tool_cards` JSONB) so reloads keep status.

Provider selection is by model id: Anthropic ids as-is, Ollama ids as ``ollama/<tag>``
(see ``app.llm.registry``). The approval loop below is provider-neutral.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    ChatMessageIn,
    ChatModelInfo,
    ChatModelsResponse,
    ChatRequest,
    ChatSessionCreate,
    ChatSessionRead,
    ChatSessionSummary,
    ChatSessionUpdate,
    DescribeSqlRequest,
    MelToolDecisionRequest,
    MelToolDecisionResponse,
    MelToolInvocationRead,
)
from app.crypto import vault
from app.db import get_db
from app.license.entitlements import get_entitlements
from app.llm import (
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
from app.llm.anthropic_provider import ANTHROPIC_DEFAULT_MODEL, ANTHROPIC_MODELS
from app.llm.registry import list_models as registry_list_models
from app.llm.registry import provider_for
from app.mcp import audit as mel_audit
from app.mcp import tools as mcp_tools
from app.mcp.approval import (
    args_summary,
    needs_approval,
    outcome_summary,
    register_proposal,
    resolve_decision,
    wait_decision,
)
from app.mcp.state import get_active_connection
from app.models.chat_session import ChatSession
from app.models.mel_tool_invocation import MelToolInvocation
from app.settings_store import get_anthropic_key, get_mel_tool_approval
from app.tenancy.deps import require_tenant_context
from app.tenancy.middleware import TenantContext

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Back-compat aliases (Anthropic ids). The full selectable list now comes from app.llm.registry.
CHAT_MODELS = ANTHROPIC_MODELS
DEFAULT_MODEL = ANTHROPIC_DEFAULT_MODEL

# Stable, no dynamic content (keeps the prompt cacheable once the prefix grows in later phases).
SYSTEM_PROMPT = """\
You are Mel, DataMETL's resident database expert — a battle-scarred database engineer embedded \
in DataMETL, a local-first tool for migrating and validating databases. Your user is an \
operator working with real production data. If asked who you are, you're Mel; otherwise don't \
over-introduce yourself — just help.

## Who you are
You're the senior DBA every team wishes they had on call: tough, direct, and allergic to \
bullshit — but genuinely in the operator's corner. You've been paged at 3am for a botched \
migration, watched a `DELETE` without a `WHERE` take down prod, and rebuilt a corrupted cluster \
from WAL. That history shows: you're calm under pressure and you do not panic.
- **No fluff, no hedging-to-be-liked.** Say the real thing. If an idea is bad, say it's bad and \
say why — plainly, never condescendingly. You explain so the operator walks away sharper, not \
talked-down-to.
- **Tough but kind.** You hold a high bar and you'll push back hard on a risky move, but it \
comes from respect: you want them to succeed and to keep their data intact. A little dry wit is \
welcome; cruelty never is.
- **Honest to a fault.** You'd rather say "I don't know — show me the DDL" than bluff a \
plausible-sounding answer. Trust is your whole value. You earn it by being right, and by owning \
it fast when you're not.
- **When it comes to databases, you mean business.** Precise, exacting, careful. Names, types, \
isolation levels, lock modes, dialect quirks — you get them right.

## Your expertise
- **Relational engines:** PostgreSQL, MySQL/MariaDB, Microsoft SQL Server (T-SQL), Oracle (PL/\
SQL), SQLite, and friends. Dialect differences, data types, indexing strategy, query planning \
and EXPLAIN, transactions/isolation/locking/MVCC, partitioning, replication, backup & restore, \
and performance tuning across all of them.
- **NoSQL & beyond:** document (MongoDB), key-value/cache (Redis), wide-column (Cassandra/\
Scylla, DynamoDB and single-table design), search (Elasticsearch/OpenSearch), and graph \
(Neo4j). Data modeling trade-offs, consistency models, and honest guidance on when NOT to reach \
for them.
- **Migration & data movement:** schema diffing, type mapping and lossy conversions, bulk load/\
COPY, batching, FK-dependency ordering, deferring/replicating constraints, sequence/identity \
resync, idempotent/repeatable loads, conflict modes (truncate vs append), verification (row \
counts, hashing, sequence parity), cutover and rollback planning, cross-engine moves, and \
minimizing downtime.
- **Operations:** managed databases (RDS/Aurora, Cloud SQL, Azure SQL) and what bites them — \
storage/IOPS/WAL and TransactionLogsDiskUsage, autoscaling limits, inactive replication slots, \
connection pooling, HA, and backups. PostgreSQL internals run deep, including Supabase \
specifics (RLS policies, the auth/storage schemas, FKs to auth.users) when they're relevant.

## How to answer
- Lead with the recommendation or answer, then the reasoning. Concise and practical — skip \
filler and over-explanation.
- Write SQL in fenced ```sql blocks, in the dialect that fits the question; when the engine \
isn't specified, default to PostgreSQL (DataMETL's home turf) and call out dialect gotchas if \
they'd port the query elsewhere.
- Flag risk loudly. Mark anything destructive or lock-taking, note when something needs a \
maintenance window or downtime, and default to the safe, reversible path. Never hand over a \
`DROP`/`TRUNCATE`/`DELETE`/`UPDATE` without its guardrails (a `WHERE`, a backup, a transaction) \
unless the operator explicitly wants the loaded gun.
- When the answer depends on specifics you don't have, ask — the DDL, the table's `\\d` output, \
the exact error text, row counts, the engine and version — rather than guessing. Concrete beats \
plausible.
- Right-size depth: a quick lookup gets a short answer; a migration-design question gets the \
trade-offs plus a recommended approach.

## Working inside DataMETL
- DataMETL's core workflow is migrating and validating PostgreSQL databases, but you advise \
across every engine above.
- By default you can't directly touch the operator's databases — reason from what they share \
and ask for schema/DDL/errors when you need them. The operator can run SQL against their \
connections from DataMETL's "SQL Scripts" page (read-only by default), so investigative queries \
you suggest — counts, sizes, catalog lookups — should be ready to paste and run there.
- When a connection is activated as a live **read-only** target, you'll be told so explicitly \
and given tools to inspect and query it directly. Until then, don't assume you can execute \
anything yourself.
- DataMETL never writes to a migration's source database and surfaces source-only tables as \
DDL preview for the operator to run themselves. Keep your advice consistent with that safety \
model.

## Tool approvals (honesty)
- Some tools — especially `run_sql` — may require the operator to click **Approve** or **Deny** \
in the chat UI before they execute. You will get a normal tool_result either way.
- If a tool was **denied**, say so plainly: it did **not** run, you saw no rows, and you must \
not invent results. Offer to adjust the query or wait for approval on a retry.
- If a tool **errored**, report the error; don't pretend it succeeded.
- Never claim you inspected or queried the live database unless a tool_result actually returned \
data.

Databases are your home and where you go deep and exacting. You're not a walled garden, though \
— if the operator asks something outside databases, help them properly and in your own voice, \
just don't wander off into long detours. Be useful, then get back to the data."""


def _event(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


@router.get("/models", response_model=ChatModelsResponse)
async def list_models(db: Session = Depends(get_db)) -> ChatModelsResponse:
    """Anthropic models plus whatever the configured Ollama host reports (live)."""
    infos, default = await registry_list_models(db)
    return ChatModelsResponse(
        models=[m.id for m in infos],
        default=default,
        entries=[
            ChatModelInfo(
                id=m.id, label=m.label, provider=m.provider, supports_tools=m.supports_tools
            )
            for m in infos
        ],
    )


# Read-only DB tools Mel gets when a connection is the active MCP target.
DB_TOOLS: list[ToolSpec] = [
    {
        "name": "list_tables",
        "description": "List the user tables (schema and name) in the connected database.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "describe_table",
        "description": "Get the columns (name, data type, nullability, default) of one table.",
        "input_schema": {
            "type": "object",
            "properties": {"schema": {"type": "string"}, "table": {"type": "string"}},
            "required": ["schema", "table"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run a read-only SQL query against the connected database and return the rows. "
            "Writes and DDL are rejected. Results are capped to 200 rows. May require the "
            "operator to Approve in the chat UI before it runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A read-only SQL query"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def _system_blocks(extra: str | None = None) -> list[str]:
    """Stable prefix first (providers that cache mark it), then any per-turn note."""
    blocks = [SYSTEM_PROMPT]
    if extra:
        blocks.append(extra)
    return blocks


def _execute_tool(name: str, tool_input: dict[str, Any], engine: str, creds: dict[str, Any]) -> str:
    try:
        if name == "list_tables":
            return mcp_tools.list_tables(engine, creds)
        if name == "describe_table":
            return mcp_tools.describe_table(
                engine, creds, str(tool_input.get("schema", "")), str(tool_input.get("table", ""))
            )
        if name == "run_sql":
            return mcp_tools.run_sql(engine, creds, str(tool_input.get("query", "")))
        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as e:  # tool errors come back as tool_result content, not exceptions
        return json.dumps({"error": str(e)})


async def _run_turn(
    provider: ChatProvider,
    *,
    model: str,
    system: list[str],
    messages: list[Message],
    tools: list[ToolSpec] | None,
    max_tokens: int = 8192,
) -> AsyncIterator[str | TurnEnd]:
    """Drive one provider turn, guaranteeing a TurnEnd even if the provider forgot one."""
    ended = False
    async for item in provider.stream_turn(
        model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens
    ):
        if isinstance(item, TurnEnd):
            ended = True
        yield item
    if not ended:
        yield TurnEnd(text="", tool_calls=[], stop_reason="end_turn")


async def _plain_stream(
    provider: ChatProvider, model: str, messages: list[Message]
) -> AsyncIterator[str]:
    """Mel's plain chat (no MCP) — NDJSON token events."""
    system = _system_blocks()
    try:
        async for item in _run_turn(
            provider, model=model, system=system, messages=messages, tools=None
        ):
            if isinstance(item, str) and item:
                yield _event({"type": "token", "text": item})
        yield _event({"type": "done"})
    except ProviderError as e:
        yield _event({"type": "error", "message": str(e)})
        yield _event({"type": "done"})
    except Exception as e:  # never leak a traceback into the chat
        yield _event({"type": "error", "message": str(e)})
        yield _event({"type": "done"})


async def _tool_loop_stream(
    provider: ChatProvider,
    model: str,
    messages: list[Message],
    *,
    conn_id: uuid.UUID,
    conn_name: str,
    engine: str,
    creds: dict[str, Any],
    approval_mode: str,
    session_id: uuid.UUID | None,
) -> AsyncIterator[str]:
    """Streaming tool-use loop with optional Approve/Deny for Mel DB tools (provider-neutral)."""
    note = (
        f"You are connected, READ-ONLY, to the database '{conn_name}' (engine: {engine}). Use the "
        "list_tables, describe_table, and run_sql tools to inspect and query it for the operator. "
        "Only read queries are possible — writes and DDL are rejected. Prefer running a query to "
        "verify rather than guessing. Some tools (especially run_sql) may wait for the operator to "
        "Approve or Deny in the UI; if denied, say so and do not invent results."
    )
    system = _system_blocks(note)
    msgs: list[Message] = list(messages)
    try:
        for _ in range(8):  # cap tool round-trips
            end: TurnEnd | None = None
            async for item in _run_turn(
                provider, model=model, system=system, messages=msgs, tools=DB_TOOLS
            ):
                if isinstance(item, TurnEnd):
                    end = item
                elif item:
                    yield _event({"type": "token", "text": item})
            assert end is not None  # _run_turn guarantees it
            if not end.wants_tools:
                yield _event({"type": "done"})
                return
            msgs.append(assistant_message(end))
            tool_results: list[ToolResult] = []
            for call in end.tool_calls:
                async for ev, result in _handle_tool_call(
                    call,
                    model=model,
                    engine=engine,
                    creds=creds,
                    approval_mode=approval_mode,
                    session_id=session_id,
                    conn_id=conn_id,
                    conn_name=conn_name,
                ):
                    if ev:
                        yield ev
                    if result is not None:
                        tool_results.append(result)
            msgs.append(tool_results_message(tool_results))
        yield _event({"type": "token", "text": "\n\n[stopped: too many tool calls in one turn]"})
        yield _event({"type": "done"})
    except ProviderError as e:
        yield _event({"type": "error", "message": str(e)})
        yield _event({"type": "done"})
    except Exception as e:  # never leak a traceback into the chat
        yield _event({"type": "error", "message": str(e)})
        yield _event({"type": "done"})


async def _handle_tool_call(
    call: ToolCall,
    *,
    model: str,
    engine: str,
    creds: dict[str, Any],
    approval_mode: str,
    session_id: uuid.UUID | None,
    conn_id: uuid.UUID,
    conn_name: str,
) -> AsyncIterator[tuple[str | None, ToolResult | None]]:
    """Approve/Deny gate + execution + audit for one tool call.

    Yields (ndjson_event, None) for UI events and finally (None, ToolResult) once.
    """
    tool_input = dict(call.input) if call.input else {}
    proposal_id = uuid.uuid4()
    summary = args_summary(call.name, tool_input)
    require = needs_approval(call.name, approval_mode)

    if require:
        mel_audit.create_invocation(
            proposal_id=proposal_id,
            tool_name=call.name,
            tool_input=tool_input,
            decision="pending",
            model=model,
            session_id=session_id,
            connection_id=conn_id,
            connection_name=conn_name,
        )
        await register_proposal(proposal_id)
        yield (
            _event({
                "type": "tool_pending",
                "proposal_id": str(proposal_id),
                "name": call.name,
                "args": tool_input,
                "args_summary": summary,
                "status": "pending",
            }),
            None,
        )
        decision = await wait_decision(proposal_id)
        if decision != "approve":
            denied_payload = json.dumps({
                "error": "Tool denied by operator — not executed.",
                "denied": True,
            })
            mel_audit.finish_invocation(
                proposal_id,
                decision="denied",
                outcome="denied",
                outcome_detail=outcome_summary(denied_payload, denied=True),
            )
            yield (
                _event({
                    "type": "tool_result",
                    "proposal_id": str(proposal_id),
                    "name": call.name,
                    "args_summary": summary,
                    "status": "denied",
                    "outcome_summary": outcome_summary(denied_payload, denied=True),
                }),
                None,
            )
            yield (None, ToolResult(call=call, content=denied_payload, is_error=True))
            return
        decision_label = "approved"
    else:
        decision_label = "auto"
        mel_audit.create_invocation(
            proposal_id=proposal_id,
            tool_name=call.name,
            tool_input=tool_input,
            decision="auto",
            model=model,
            session_id=session_id,
            connection_id=conn_id,
            connection_name=conn_name,
        )
        yield (
            _event({
                "type": "tool_pending",
                "proposal_id": str(proposal_id),
                "name": call.name,
                "args": tool_input,
                "args_summary": summary,
                "status": "auto",
            }),
            None,
        )

    result = await asyncio.to_thread(_execute_tool, call.name, tool_input, engine, creds)
    err = None
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("error"):
            err = str(parsed["error"])
    except Exception:
        pass
    out_status = "error" if err else "success"
    detail = outcome_summary(result, error=err)
    mel_audit.finish_invocation(
        proposal_id,
        decision=decision_label,
        outcome=out_status,
        outcome_detail=detail,
    )
    yield (
        _event({
            "type": "tool_result",
            "proposal_id": str(proposal_id),
            "name": call.name,
            "args_summary": summary,
            "status": "approved" if decision_label == "approved" else decision_label,
            "outcome": out_status,
            "outcome_summary": detail,
        }),
        None,
    )
    yield (None, ToolResult(call=call, content=result, is_error=bool(err)))


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> StreamingResponse:
    try:
        provider, model = provider_for(db, payload.model)
    except ProviderError as e:
        raise HTTPException(400, str(e)) from e

    # Resolve everything that needs `db` now — the generator runs after this handler returns.
    messages: list[Message] = [
        user_message(m.content) if m.role == "user" else {"role": "assistant", "content": m.content}
        for m in payload.messages
    ]
    session_id = payload.session_id
    active = get_active_connection(db)
    ents = get_entitlements(db)
    approval_mode = ents.effective_mel_tool_approval(get_mel_tool_approval(db))

    if active is not None:
        creds = vault.decrypt(active.encrypted_credentials)
        gen = _tool_loop_stream(
            provider,
            model,
            messages,
            conn_id=active.id,
            conn_name=active.name,
            engine=active.engine,
            creds=creds,
            approval_mode=approval_mode,
            session_id=session_id,
        )
    else:
        gen = _plain_stream(provider, model, messages)
    return StreamingResponse(gen, media_type="application/x-ndjson; charset=utf-8")


@router.post("/tool-decision", response_model=MelToolDecisionResponse)
async def tool_decision(
    payload: MelToolDecisionRequest,
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> MelToolDecisionResponse:
    """Approve or deny a pending Mel tool proposal from the chat UI."""
    ok = await resolve_decision(payload.proposal_id, payload.decision)
    if not ok:
        raise HTTPException(404, "No pending tool proposal with that id (already decided or expired).")
    return MelToolDecisionResponse(
        ok=True, proposal_id=payload.proposal_id, decision=payload.decision
    )


@router.get("/mel-audit", response_model=list[MelToolInvocationRead])
def list_mel_audit(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> list[MelToolInvocation]:
    """Recent Mel tool invocations (redacted args) for the audit / activity surfaces."""
    rows = list(
        db.execute(
            select(MelToolInvocation).order_by(MelToolInvocation.created_at.desc()).limit(limit)
        ).scalars()
    )
    return rows


# --- Describe a SQL script (used by the Scripts editor's "Generate with Mel" button) ---

# Default for this tight single-shot task: Sonnet when an Anthropic key exists, else the
# first local Ollama model (resolved per request in describe_sql).
DESCRIBE_SQL_MODEL = "claude-sonnet-4-6"

DESCRIBE_SQL_SYSTEM = """\
You are Mel, DataMETL's database expert. The operator gives you a SQL script and you write a \
clear, concise description of what it does, for documentation that lives next to the script.

Output Markdown only — no preamble, no sign-off, no conversational filler:
- Open with a single bold one-line summary of the script's purpose.
- Then a short bulleted breakdown: the tables/objects it touches, what each statement does, and \
notable filters, joins, aggregations, or ordering.
- Call out side effects and risk plainly: flag anything that writes or is destructive \
(INSERT/UPDATE/DELETE/TRUNCATE/DROP/DDL); if it's purely a read, say so.
- Note the SQL dialect only if the script uses dialect-specific syntax.

Keep it tight and skimmable. Do not echo the SQL back verbatim. If the input isn't valid SQL or \
is empty, say so in one line."""


async def _describe_stream(provider: ChatProvider, model: str, sql: str) -> AsyncIterator[str]:
    system = [DESCRIBE_SQL_SYSTEM]
    messages: list[Message] = [user_message(f"```sql\n{sql}\n```")]
    try:
        async for item in _run_turn(
            provider, model=model, system=system, messages=messages, tools=None, max_tokens=1024
        ):
            if isinstance(item, str) and item:
                yield item
    except ProviderError as e:
        yield f"\n\n[error: {e}]"
    except Exception as e:  # never leak a traceback
        yield f"\n\n[error: {e}]"


async def _default_describe_model(db: Session) -> str:
    if get_anthropic_key(db) is not None:
        return DESCRIBE_SQL_MODEL
    _, default = await registry_list_models(db)
    return default


@router.post("/describe-sql")
async def describe_sql(
    payload: DescribeSqlRequest,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> StreamingResponse:
    sql = payload.sql.strip()
    if not sql:
        raise HTTPException(400, "No SQL to describe — write the script first.")
    model = payload.model or await _default_describe_model(db)
    try:
        provider, model = provider_for(db, model)
    except ProviderError as e:
        raise HTTPException(400, str(e)) from e
    return StreamingResponse(
        _describe_stream(provider, model, sql), media_type="text/plain; charset=utf-8"
    )


# --- Persisted chat sessions ---

def _derive_title(messages: list[ChatMessageIn]) -> str:
    """Title a saved chat from its first user message; fall back to 'New chat'."""
    for m in messages:
        if m.role == "user" and m.content.strip():
            t = " ".join(m.content.split())[:60]
            return t or "New chat"
    return "New chat"


def _tool_cards_from_row(row: ChatSession) -> list:
    """Coerce stored JSONB tool_cards (may be missing on pre-migration rows) to schema list."""
    raw = getattr(row, "tool_cards", None) or []
    if not isinstance(raw, list):
        return []
    return raw


def _to_read(row: ChatSession) -> ChatSessionRead:
    return ChatSessionRead(
        id=row.id,
        title=row.title,
        model=row.model,
        messages=row.messages,
        tool_cards=_tool_cards_from_row(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions(
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> list[ChatSessionSummary]:
    rows = db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc())).scalars()
    return [
        ChatSessionSummary(
            id=r.id, title=r.title, model=r.model, message_count=len(r.messages or []),
            created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> ChatSessionRead:
    title = (payload.title or "").strip() or _derive_title(payload.messages)
    row = ChatSession(
        title=title,
        model=payload.model,
        messages=[m.model_dump() for m in payload.messages],
        tool_cards=[c.model_dump() for c in payload.tool_cards],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> ChatSessionRead:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    return _to_read(row)


@router.put("/sessions/{session_id}", response_model=ChatSessionRead)
def update_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdate,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> ChatSessionRead:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    row.messages = [m.model_dump() for m in payload.messages]
    if payload.tool_cards is not None:
        row.tool_cards = [c.model_dump() for c in payload.tool_cards]
    if payload.model:
        row.model = payload.model
    if payload.title and payload.title.strip():
        row.title = payload.title.strip()
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    _tenant: TenantContext | None = Depends(require_tenant_context),
) -> None:
    row = db.get(ChatSession, session_id)
    if row is None:
        raise HTTPException(404, "Chat session not found")
    db.delete(row)
    db.commit()
