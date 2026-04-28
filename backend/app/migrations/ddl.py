"""Generate human-readable CREATE TABLE / CREATE INDEX SQL from a snapshot's `Table`.

Pure string output — never executes. Used by pre-flight to surface ready-to-run SQL for
tables that exist on source but not destination (since v1 doesn't auto-CREATE).

The DDL targets vanilla Postgres syntax. Defaults are reproduced verbatim from the source
snapshot, which means Supabase-specific defaults like `gen_random_uuid()` show up as-is —
the user's job to ensure the destination has pgcrypto (or PG14+) before running.
"""
from __future__ import annotations

from app.introspection.normalized import Column, Table


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def create_table_sql(table: Table, *, schema_override: str | None = None) -> str:
    """Generate a CREATE TABLE statement for a normalized Table.

    `schema_override` lets callers retarget the table to a different destination schema
    (e.g. moving `public.posts` to `legacy.posts`).
    """
    schema = schema_override or table.schema_
    lines: list[str] = []
    lines.append(f"CREATE TABLE IF NOT EXISTS {_quote(schema)}.{_quote(table.name)} (")

    col_lines = [_column_def(c) for c in table.columns]

    pk_cols = [c.name for c in table.columns if c.is_primary_key]
    if pk_cols:
        col_lines.append(f"    PRIMARY KEY ({', '.join(_quote(c) for c in pk_cols)})")

    lines.append(",\n".join(col_lines))
    lines.append(");")
    return "\n".join(lines)


def _column_def(col: Column) -> str:
    parts = [f"    {_quote(col.name)} {col.native_type}"]
    if not col.nullable:
        parts.append("NOT NULL")
    if col.default is not None:
        parts.append(f"DEFAULT {col.default}")
    return " ".join(parts)


def create_index_sql(table: Table, *, schema_override: str | None = None) -> list[str]:
    """One CREATE INDEX statement per non-primary-key index."""
    schema = schema_override or table.schema_
    out: list[str] = []
    for idx in table.indexes:
        # Skip implicit PK indexes (Postgres creates them automatically with the PK constraint).
        if idx.name.endswith("_pkey"):
            continue
        unique = "UNIQUE " if idx.unique else ""
        cols = ", ".join(_quote(c) for c in idx.columns)
        out.append(
            f"CREATE {unique}INDEX IF NOT EXISTS {_quote(idx.name)} "
            f"ON {_quote(schema)}.{_quote(table.name)} ({cols});"
        )
    return out


def full_ddl(table: Table, *, schema_override: str | None = None) -> str:
    """Convenience: CREATE TABLE plus all CREATE INDEX statements as one string."""
    parts = [create_table_sql(table, schema_override=schema_override)]
    parts.extend(create_index_sql(table, schema_override=schema_override))
    return "\n\n".join(parts)
