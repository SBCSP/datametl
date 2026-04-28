"""Default datatype mappings between engines.

For Phase 1 (Postgres → Postgres) the mapping is mostly identity: we keep the source
native type. For cross-engine cases the registry will pick a sensible default per
(source_engine, source_normalized_type, dest_engine).
"""
from __future__ import annotations

from app.introspection.normalized import NormalizedType

# Native type to default to per (dest_engine, normalized_type) when there's no source-native string to preserve.
_DEFAULT_DEST_NATIVE: dict[tuple[str, NormalizedType], str] = {
    ("postgres", "string"): "text",
    ("postgres", "int16"): "smallint",
    ("postgres", "int32"): "integer",
    ("postgres", "int64"): "bigint",
    ("postgres", "float32"): "real",
    ("postgres", "float64"): "double precision",
    ("postgres", "decimal"): "numeric",
    ("postgres", "boolean"): "boolean",
    ("postgres", "uuid"): "uuid",
    ("postgres", "json"): "jsonb",
    ("postgres", "binary"): "bytea",
    ("postgres", "date"): "date",
    ("postgres", "time"): "time",
    ("postgres", "timestamp"): "timestamp",
    ("postgres", "timestamptz"): "timestamptz",
    ("postgres", "interval"): "interval",
    ("postgres", "array"): "text[]",
    ("postgres", "enum"): "text",
    ("postgres", "geometry"): "geometry",
    ("postgres", "unknown"): "text",
}


def default_dest_type(
    source_engine: str,
    source_native: str,
    source_normalized: NormalizedType,
    dest_engine: str,
) -> str:
    """Pick the default destination native type.

    Same-engine: preserve the source native type verbatim (Postgres → Postgres keeps
    `varchar(255)`, `numeric(10,2)`, etc.). Cross-engine: fall back to the registry default
    keyed on normalized type.
    """
    if source_engine == dest_engine:
        return source_native
    return _DEFAULT_DEST_NATIVE.get((dest_engine, source_normalized), "text")


# A small set of conversions that are known to be lossy regardless of widths.
# Width-narrowing (e.g. varchar(255) → varchar(100)) is detected separately at override time.
_LOSSY_PAIRS: frozenset[tuple[NormalizedType, NormalizedType]] = frozenset(
    {
        ("timestamptz", "timestamp"),    # tz dropped
        ("timestamptz", "date"),
        ("timestamp", "date"),
        ("float64", "float32"),
        ("int64", "int32"),
        ("int64", "int16"),
        ("int32", "int16"),
        ("decimal", "float64"),
        ("decimal", "float32"),
        ("json", "string"),
        ("array", "string"),
    }
)


def is_lossy(source_normalized: NormalizedType, dest_normalized: NormalizedType) -> bool:
    if source_normalized == dest_normalized:
        return False
    return (source_normalized, dest_normalized) in _LOSSY_PAIRS
