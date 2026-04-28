"""Pure-function tests for the Postgres native-type → normalized-type mapping.

The full introspector that hits a live DB is exercised end-to-end via the sample compose
profile (`make up-samples` then introspect from the UI). That isn't a unit test.
"""
from __future__ import annotations

import pytest

from app.introspection.postgres import _normalize_type


@pytest.mark.parametrize(
    "native,expected",
    [
        ("text", "string"),
        ("character varying(255)", "string"),
        ("varchar", "string"),
        ("citext", "string"),
        ("smallint", "int16"),
        ("integer", "int32"),
        ("bigint", "int64"),
        ("real", "float32"),
        ("double precision", "float64"),
        ("numeric(10,2)", "decimal"),
        ("boolean", "boolean"),
        ("uuid", "uuid"),
        ("jsonb", "json"),
        ("json", "json"),
        ("bytea", "binary"),
        ("date", "date"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp with time zone", "timestamptz"),
        ("timestamptz", "timestamptz"),
        ("interval", "interval"),
        ("text[]", "array"),
        ("_int4", "array"),
        ("some_user_defined_type", "unknown"),
    ],
)
def test_normalize_type(native: str, expected: str) -> None:
    assert _normalize_type(native) == expected
