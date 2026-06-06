"""Land fetched JSON records into a destination Postgres connection as JSONB rows.

Auto-creates a simple landing table (we own its shape): one row per record, the raw JSON kept in a
`data jsonb` column with a `fetched_at` timestamp and the source name. Schemaless on purpose — the
DBA flattens/transforms later with SQL or an ETL pipeline.
"""
from __future__ import annotations

import json
from typing import Any

from app.connectors.postgres import PostgresConnector


def _split_qn(qn: str) -> tuple[str, str]:
    if "." in qn:
        s, _, t = qn.partition(".")
        return s.strip(), t.strip()
    return "public", qn.strip()


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def land_records(
    creds: dict[str, Any], dest_table: str, source: str, records: list[Any], mode: str
) -> dict[str, Any]:
    """Create the landing table if missing, optionally TRUNCATE (mode='replace'), then bulk-insert
    each record as a JSONB row. Returns {rows_written}. Atomic per destination."""
    if not dest_table.strip():
        raise ValueError("destination table is required")
    if mode not in ("append", "replace"):
        raise ValueError(f"unknown write mode: {mode}")

    schema, name = _split_qn(dest_table)
    qual = f"{_q(schema)}.{_q(name)}"
    create_sql = (
        f"CREATE TABLE IF NOT EXISTS {qual} ("
        "id bigserial PRIMARY KEY, "
        "fetched_at timestamptz NOT NULL DEFAULT now(), "
        "source text, "
        "data jsonb NOT NULL)"
    )
    if schema != "public":
        create_schema_sql = f"CREATE SCHEMA IF NOT EXISTS {_q(schema)}"
    else:
        create_schema_sql = None

    engine = PostgresConnector(creds)._engine()
    rows_written = 0
    raw = engine.raw_connection()
    try:
        conn: Any = raw.driver_connection  # psycopg.Connection
        try:
            conn.rollback()
        except Exception:  # clear any stray txn state
            pass
        with conn.cursor() as cur:
            if create_schema_sql:
                cur.execute(create_schema_sql)
            cur.execute(create_sql)
            if mode == "replace":
                cur.execute(f"TRUNCATE TABLE {qual}")
            if records:
                cur.executemany(
                    f"INSERT INTO {qual} (source, data) VALUES (%s, %s::jsonb)",
                    [(source, json.dumps(r)) for r in records],
                )
                rows_written = len(records)
        conn.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
        raise
    finally:
        raw.close()
        engine.dispose()
    return {"rows_written": rows_written}
