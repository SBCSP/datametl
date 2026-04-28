from __future__ import annotations

from app.mapping.registry import default_dest_type, is_lossy


def test_same_engine_preserves_native_type():
    assert default_dest_type("postgres", "varchar(255)", "string", "postgres") == "varchar(255)"
    assert default_dest_type("postgres", "numeric(10,2)", "decimal", "postgres") == "numeric(10,2)"


def test_cross_engine_uses_registry_default():
    # Pretend a non-postgres source maps "string" → text on Postgres dest
    assert default_dest_type("mysql", "longtext", "string", "postgres") == "text"


def test_lossy_pairs():
    assert is_lossy("timestamptz", "timestamp")
    assert is_lossy("int64", "int32")
    assert is_lossy("decimal", "float64")


def test_non_lossy_pairs():
    assert not is_lossy("string", "string")
    assert not is_lossy("int32", "int64")          # widening
    assert not is_lossy("timestamp", "timestamptz") # adding tz info isn't lossy
