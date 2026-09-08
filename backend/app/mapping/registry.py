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
    # MySQL destination defaults (used when comparing into a MySQL target). Data migration
    # between engines is not wired yet; these keep cross-engine comparison/mapping sensible.
    ("mysql", "string"): "TEXT",
    ("mysql", "int16"): "SMALLINT",
    ("mysql", "int32"): "INT",
    ("mysql", "int64"): "BIGINT",
    ("mysql", "float32"): "FLOAT",
    ("mysql", "float64"): "DOUBLE",
    ("mysql", "decimal"): "DECIMAL",
    ("mysql", "boolean"): "TINYINT(1)",
    ("mysql", "uuid"): "CHAR(36)",
    ("mysql", "json"): "JSON",
    ("mysql", "binary"): "BLOB",
    ("mysql", "date"): "DATE",
    ("mysql", "time"): "TIME",
    ("mysql", "timestamp"): "DATETIME",
    ("mysql", "timestamptz"): "DATETIME",
    ("mysql", "interval"): "VARCHAR(64)",
    ("mysql", "array"): "JSON",
    ("mysql", "enum"): "TEXT",
    ("mysql", "geometry"): "GEOMETRY",
    ("mysql", "unknown"): "TEXT",
    # SQL Server destination defaults (connect + introspect/compare; cross-engine migrate TBD).
    ("mssql", "string"): "NVARCHAR(MAX)",
    ("mssql", "int16"): "SMALLINT",
    ("mssql", "int32"): "INT",
    ("mssql", "int64"): "BIGINT",
    ("mssql", "float32"): "REAL",
    ("mssql", "float64"): "FLOAT",
    ("mssql", "decimal"): "DECIMAL(18,6)",
    ("mssql", "boolean"): "BIT",
    ("mssql", "uuid"): "UNIQUEIDENTIFIER",
    ("mssql", "json"): "NVARCHAR(MAX)",
    ("mssql", "binary"): "VARBINARY(MAX)",
    ("mssql", "date"): "DATE",
    ("mssql", "time"): "TIME",
    ("mssql", "timestamp"): "DATETIME2",
    ("mssql", "timestamptz"): "DATETIMEOFFSET",
    ("mssql", "interval"): "NVARCHAR(64)",
    ("mssql", "array"): "NVARCHAR(MAX)",
    ("mssql", "enum"): "NVARCHAR(255)",
    ("mssql", "geometry"): "GEOMETRY",
    ("mssql", "unknown"): "NVARCHAR(MAX)",
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
