from __future__ import annotations

from app.migrations.ddl import create_index_sql, create_table_sql, full_ddl
from tests._factories import col, tbl


def test_basic_create_table():
    t = tbl("public", "posts", [
        col("id", "uuid", "uuid", pk=True, nullable=False),
        col("title", "varchar(255)", "string", nullable=False),
        col("body", "text", "string"),
    ])
    sql = create_table_sql(t)
    assert 'CREATE TABLE IF NOT EXISTS "public"."posts"' in sql
    assert '"id" uuid NOT NULL' in sql
    assert '"title" varchar(255) NOT NULL' in sql
    assert '"body" text' in sql
    assert 'PRIMARY KEY ("id")' in sql


def test_create_table_preserves_default():
    t = tbl("public", "users", [
        col("id", "uuid", "uuid", pk=True, nullable=False, default="gen_random_uuid()"),
    ])
    sql = create_table_sql(t)
    assert 'DEFAULT gen_random_uuid()' in sql


def test_schema_override_retargets_create():
    t = tbl("public", "posts", [col("id", "uuid", "uuid", pk=True, nullable=False)])
    sql = create_table_sql(t, schema_override="legacy")
    assert '"legacy"."posts"' in sql
    assert '"public"."posts"' not in sql


def test_create_index_skips_pkey_implicit():
    from app.introspection.normalized import Index

    t = tbl(
        "public", "posts",
        [col("id", "uuid", "uuid", pk=True, nullable=False)],
        indexes=[
            Index(name="posts_pkey", columns=["id"], unique=True),
            Index(name="posts_title_idx", columns=["title"]),
        ],
    )
    out = create_index_sql(t)
    assert len(out) == 1
    assert 'posts_title_idx' in out[0]


def test_full_ddl_concatenates_table_and_indexes():
    from app.introspection.normalized import Index

    t = tbl(
        "public", "posts",
        [col("id", "uuid", "uuid", pk=True, nullable=False)],
        indexes=[Index(name="posts_x", columns=["x"])],
    )
    sql = full_ddl(t)
    assert 'CREATE TABLE IF NOT EXISTS' in sql
    assert 'CREATE INDEX IF NOT EXISTS' in sql
