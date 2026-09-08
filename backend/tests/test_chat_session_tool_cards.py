"""Chat session tool_cards sidecar — persist/reload without a live DB."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.api import chat as chat_api
from app.api.schemas_io import (
    ChatMessageIn,
    ChatSessionCreate,
    ChatSessionRead,
    ChatSessionUpdate,
    MelToolCardIn,
)
from app.models.chat_session import ChatSession


def _card(**kw) -> MelToolCardIn:
    base = {
        "proposal_id": str(uuid.uuid4()),
        "name": "run_sql",
        "args_summary": "SELECT 1",
        "args": {"query": "SELECT 1"},
        "status": "success",
        "outcome_summary": "1 row",
    }
    base.update(kw)
    return MelToolCardIn(**base)


def test_mel_tool_card_schema_roundtrip() -> None:
    card = _card(status="denied", outcome_summary="Denied by operator — not executed")
    dumped = card.model_dump()
    again = MelToolCardIn.model_validate(dumped)
    assert again.status == "denied"
    assert again.name == "run_sql"
    assert again.args["query"] == "SELECT 1"


def test_mel_tool_card_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        MelToolCardIn(
            proposal_id=str(uuid.uuid4()),
            name="run_sql",
            status="nope",  # type: ignore[arg-type]
        )


def test_session_create_schema_includes_tool_cards() -> None:
    payload = ChatSessionCreate(
        model="claude-opus-4-8",
        messages=[ChatMessageIn(role="user", content="hi")],
        tool_cards=[_card()],
    )
    assert len(payload.tool_cards) == 1
    assert payload.tool_cards[0].status == "success"


def test_session_update_tool_cards_optional() -> None:
    # Omitted / None means leave unchanged at the API layer
    payload = ChatSessionUpdate(
        messages=[ChatMessageIn(role="user", content="hi")],
    )
    assert payload.tool_cards is None

    payload2 = ChatSessionUpdate(
        messages=[ChatMessageIn(role="user", content="hi")],
        tool_cards=[],
    )
    assert payload2.tool_cards == []


def test_to_read_includes_tool_cards() -> None:
    now = datetime.now(UTC)
    cards = [_card(status="auto").model_dump(), _card(status="error").model_dump()]
    row = ChatSession(
        id=uuid.uuid4(),
        title="hello",
        model="claude-opus-4-8",
        messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
        tool_cards=cards,
        created_at=now,
        updated_at=now,
    )
    read = chat_api._to_read(row)
    assert isinstance(read, ChatSessionRead)
    assert len(read.tool_cards) == 2
    assert {c.status for c in read.tool_cards} == {"auto", "error"}


def test_to_read_defaults_missing_tool_cards() -> None:
    now = datetime.now(UTC)
    row = MagicMock(spec=ChatSession)
    row.id = uuid.uuid4()
    row.title = "x"
    row.model = "claude-opus-4-8"
    row.messages = []
    row.tool_cards = None  # pre-migration / unset
    row.created_at = now
    row.updated_at = now
    read = chat_api._to_read(row)
    assert read.tool_cards == []


def test_create_session_persists_tool_cards() -> None:
    db = MagicMock()
    # db.add + commit + refresh: simulate refresh leaving attributes on the row
    created_cards = [_card(status="denied").model_dump()]

    def refresh(row: ChatSession) -> None:
        if row.id is None:
            row.id = uuid.uuid4()
        row.created_at = datetime.now(UTC)
        row.updated_at = row.created_at
        # ensure tool_cards stick
        assert row.tool_cards == created_cards

    db.refresh.side_effect = refresh

    payload = ChatSessionCreate(
        model="claude-opus-4-8",
        messages=[
            ChatMessageIn(role="user", content="list tables"),
            ChatMessageIn(role="assistant", content="done"),
        ],
        tool_cards=[MelToolCardIn.model_validate(created_cards[0])],
    )
    result = chat_api.create_session(payload, db)
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, ChatSession)
    assert added.tool_cards == created_cards
    assert len(result.tool_cards) == 1
    assert result.tool_cards[0].status == "denied"


def test_update_session_replaces_tool_cards() -> None:
    db = MagicMock()
    now = datetime.now(UTC)
    sid = uuid.uuid4()
    row = ChatSession(
        id=sid,
        title="t",
        model="claude-opus-4-8",
        messages=[{"role": "user", "content": "a"}],
        tool_cards=[_card(status="pending").model_dump()],
        created_at=now,
        updated_at=now,
    )
    db.get.return_value = row

    new_cards = [_card(status="success", outcome_summary="ok")]
    payload = ChatSessionUpdate(
        messages=[
            ChatMessageIn(role="user", content="a"),
            ChatMessageIn(role="assistant", content="b"),
        ],
        tool_cards=new_cards,
    )
    result = chat_api.update_session(sid, payload, db)
    assert row.tool_cards == [c.model_dump() for c in new_cards]
    assert result.tool_cards[0].status == "success"
    db.commit.assert_called()


def test_update_session_leaves_tool_cards_when_omitted() -> None:
    db = MagicMock()
    now = datetime.now(UTC)
    sid = uuid.uuid4()
    original = [_card(status="auto").model_dump()]
    row = ChatSession(
        id=sid,
        title="t",
        model="claude-opus-4-8",
        messages=[{"role": "user", "content": "a"}],
        tool_cards=original,
        created_at=now,
        updated_at=now,
    )
    db.get.return_value = row

    payload = ChatSessionUpdate(
        messages=[ChatMessageIn(role="user", content="a")],
        tool_cards=None,
    )
    chat_api.update_session(sid, payload, db)
    assert row.tool_cards == original
