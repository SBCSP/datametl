from __future__ import annotations

from app.recipes.supabase import analyze
from tests._factories import col, fk, policy, schema, tbl, view


def _codes(warnings) -> set[str]:
    return {w.code for w in warnings}


def test_flags_supabase_schemas():
    s = schema([tbl("auth", "users", [col("id", "uuid", "uuid", pk=True)])])
    assert "supabase.schemas_present" in _codes(analyze(s))


def test_flags_gen_random_uuid_default():
    s = schema([
        tbl("public", "posts", [
            col("id", "uuid", "uuid", pk=True, default="gen_random_uuid()"),
        ])
    ])
    assert "supabase.gen_random_uuid_default" in _codes(analyze(s))


def test_flags_fk_to_auth_users():
    s = schema([
        tbl("public", "profiles", [
            col("id", "uuid", "uuid", pk=True, fk=fk("auth", "users", "id")),
        ])
    ])
    assert "supabase.fk_to_auth_users" in _codes(analyze(s))


def test_flags_rls_enabled_table():
    s = schema([
        tbl("public", "posts", [col("id", "uuid", "uuid", pk=True)], rls=True),
    ])
    assert "supabase.rls_enabled" in _codes(analyze(s))


def test_flags_policy_using_auth_helper():
    s = schema(
        [tbl("public", "posts", [col("id", "uuid", "uuid", pk=True)])],
        policies=[policy("public", "posts", "p1", using="auth.uid() = author_id")],
    )
    assert "supabase.policy_uses_auth_helper" in _codes(analyze(s))


def test_flags_view_using_auth_helper():
    s = schema(
        [tbl("public", "posts", [col("id", "uuid", "uuid", pk=True)])],
        views=[view("public", "my_posts", "SELECT * FROM public.posts WHERE author_id = auth.uid()")],
    )
    assert "supabase.view_uses_auth_helper" in _codes(analyze(s))


def test_flags_supabase_only_extension():
    s = schema([tbl("public", "x", [col("id", "uuid", "uuid", pk=True)])], extensions=["pgsodium"])
    assert "supabase.extension_only_in_supabase" in _codes(analyze(s))


def test_clean_vanilla_pg_emits_no_warnings():
    s = schema([
        tbl("public", "posts", [
            col("id", "uuid", "uuid", pk=True, default="uuid_generate_v4()"),
            col("title", "text", "string"),
        ])
    ], extensions=["uuid-ossp", "pgcrypto"])
    assert _codes(analyze(s)) == set()
