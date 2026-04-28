from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.transforms.column_plan import build_column_plan


@dataclass
class _M:
    """Minimal in-memory stand-in for the Mapping ORM model."""

    source_table: str
    source_column: str
    dest_table: str
    dest_column: str
    source_type: str
    default_dest_type: str
    override_dest_type: str | None = None
    skip: bool = False
    is_lossy: bool = False
    notes: str | None = None
    id: uuid.UUID = uuid.uuid4()
    comparison_id: uuid.UUID = uuid.uuid4()


def test_identity_mapping_no_cast_no_alias():
    plan = build_column_plan([
        _M("public.posts", "id", "public.posts", "id", "uuid", "uuid"),
        _M("public.posts", "title", "public.posts", "title", "text", "text"),
    ])
    assert plan.select_exprs == ['"id"', '"title"']
    assert plan.dest_columns == ['"id"', '"title"']
    assert plan.skipped == []


def test_type_cast_when_dest_type_differs():
    plan = build_column_plan([
        _M("public.posts", "title", "public.posts", "title", "text", "text", override_dest_type="varchar(100)"),
    ])
    assert plan.select_exprs == ['("title")::varchar(100)']
    assert plan.dest_columns == ['"title"']


def test_rename_with_alias():
    plan = build_column_plan([
        _M("public.posts", "author_id", "public.posts", "user_id", "uuid", "uuid"),
    ])
    assert plan.select_exprs == ['"author_id" AS "user_id"']
    assert plan.dest_columns == ['"user_id"']


def test_cast_and_rename_combined():
    plan = build_column_plan([
        _M("public.posts", "created_at", "public.posts", "created_ts", "timestamptz", "timestamptz", override_dest_type="timestamp"),
    ])
    assert plan.select_exprs == ['("created_at")::timestamp AS "created_ts"']
    assert plan.dest_columns == ['"created_ts"']


def test_skip_drops_column_from_both_lists():
    plan = build_column_plan([
        _M("public.posts", "id", "public.posts", "id", "uuid", "uuid"),
        _M("public.posts", "secret", "public.posts", "secret", "text", "text", skip=True),
        _M("public.posts", "title", "public.posts", "title", "text", "text"),
    ])
    assert plan.select_exprs == ['"id"', '"title"']
    assert plan.dest_columns == ['"id"', '"title"']
    assert plan.skipped == ["secret"]


def test_quoting_handles_embedded_quote():
    plan = build_column_plan([
        _M("public.\"weird\"", 'co"l', "public.t", "co\"l", "text", "text"),
    ])
    assert plan.select_exprs == ['"co""l"']
    assert plan.dest_columns == ['"co""l"']
