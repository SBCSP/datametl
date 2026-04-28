from __future__ import annotations

from app.comparison import diff_schemas
from tests._factories import col, schema, tbl


def test_tables_only_in_each_side():
    src = schema([tbl("public", "users", [col("id", "uuid", "uuid", pk=True)])])
    dst = schema([tbl("public", "posts", [col("id", "uuid", "uuid", pk=True)])])

    d = diff_schemas(src, dst)

    assert d.tables_only_in_source == ["public.users"]
    assert d.tables_only_in_dest == ["public.posts"]
    assert d.common_tables == []


def test_column_drift_kinds():
    src = schema([
        tbl("public", "posts", [
            col("id", "uuid", "uuid", pk=True),
            col("title", "text", "string"),
            col("created_at", "timestamp with time zone", "timestamptz", nullable=False),
        ]),
    ])
    dst = schema([
        tbl("public", "posts", [
            col("id", "uuid", "uuid", pk=True),
            col("title", "varchar(100)", "string"),                      # type_changed (native differs)
            col("created_at", "timestamp", "timestamp", nullable=True),  # type_changed + nullable_changed
            col("extra", "integer", "int32"),                             # missing_in_source
        ]),
    ])

    d = diff_schemas(src, dst)

    assert d.tables_only_in_source == []
    assert d.tables_only_in_dest == []
    assert len(d.common_tables) == 1
    drifts = {(c.column, c.kind) for c in d.common_tables[0].column_drift}
    assert ("title", "type_changed") in drifts
    assert ("created_at", "type_changed") in drifts
    assert ("created_at", "nullable_changed") in drifts
    assert ("extra", "missing_in_source") in drifts


def test_no_drift_for_identical_tables():
    same = [tbl("public", "users", [col("id", "uuid", "uuid", pk=True, nullable=False)])]
    src = schema(same)
    dst = schema(same)

    d = diff_schemas(src, dst)
    assert d.common_tables[0].column_drift == []
