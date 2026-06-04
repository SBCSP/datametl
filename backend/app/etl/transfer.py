"""Stream the result of a source SELECT into a destination table via CSV ``COPY``.

This is the ETL pipeline's data-movement primitive. It is deliberately SEPARATE from the
migration `LogicalCopyStrategy` (which does whole-table *binary* COPY with a mapping-driven
column plan) so that nothing here can affect the working migration path.

Why CSV instead of binary: the source is an arbitrary SELECT and the destination an existing
table the operator names. Binary COPY requires the SELECT's output types to match the
destination columns *exactly*; CSV runs each destination column's input function, so compatible
text representations coerce cleanly (e.g. int → bigint, text → varchar). That forgiveness is the
right default for query→table ETL.

Safety invariants (mirrors the migration runner's guarantees):
  * Source runs under ``SET TRANSACTION READ ONLY`` — no writes can leak through this path.
  * Destination work is one transaction: TRUNCATE (optional) + COPY, committed on success and
    rolled back on any error.
  * The destination table is never auto-created — a missing table surfaces as a clear error.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("datametl.etl.transfer")


def _split_qn(qn: str) -> tuple[str, str]:
    if "." in qn:
        s, _, t = qn.partition(".")
        return s.strip(), t.strip()
    return "public", qn.strip()


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _qualified(table: str) -> str:
    schema, name = _split_qn(table)
    return f"{_q(schema)}.{_q(name)}"


def _query_columns(raw_conn: Any, source_sql: str) -> list[str]:
    """Return the output column names of ``source_sql`` without running the full query.

    Wraps it as ``SELECT * FROM (<source_sql>) LIMIT 0`` and reads the cursor description, so the
    destination COPY can target those columns by name."""
    with raw_conn.cursor() as cur:
        cur.execute(f"SELECT * FROM ({source_sql}) AS _src LIMIT 0")
        return [d.name for d in (cur.description or [])]


def stream_query_to_table(
    source_engine: Engine,
    dest_engine: Engine,
    *,
    source_sql: str,
    dest_table: str,
    dest_columns: list[str] | None = None,
    mode: str = "truncate",
) -> dict[str, Any]:
    """Stream ``source_sql``'s rows into ``dest_table`` on another connection.

    mode: "truncate" → TRUNCATE the destination first, then load; "append" → load on top.
    dest_columns: optional explicit destination column list. When omitted, the destination
    columns are derived from the source query's output column NAMES, so the load maps by name
    (and untargeted columns like an auto-generated ``id`` keep their defaults).

    Returns ``{rows_written, detail}``. Raises on any failure (the destination txn is rolled
    back, leaving the table untouched).
    """
    t0 = time.monotonic()
    source_sql = source_sql.strip().rstrip(";")
    if not source_sql:
        raise ValueError("transfer step has no source SQL")
    if mode not in ("truncate", "append"):
        raise ValueError(f"unknown transfer mode: {mode}")

    dst_qual = _qualified(dest_table)
    src_copy_sql = f"COPY ({source_sql}) TO STDOUT (FORMAT csv)"

    log.info("transfer: query → %s (mode=%s)", dest_table, mode)

    rows_written = 0
    dst_raw = dest_engine.raw_connection()
    try:
        dst_psyco: Any = dst_raw.driver_connection  # psycopg.Connection
        try:
            dst_psyco.rollback()
        except Exception:  # noqa: BLE001 — clear any stray txn state from pool listeners
            pass
        dst_psyco.autocommit = False

        with dst_psyco.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
        if mode == "truncate":
            with dst_psyco.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {dst_qual}")

        # Source: read-only, streamed out as CSV.
        with source_engine.connect() as src_conn:
            src_conn.execute(text("SET TRANSACTION READ ONLY"))
            src_conn.execute(text("SET statement_timeout = 0"))
            src_raw: Any = src_conn.connection.driver_connection  # psycopg.Connection

            # Map into the destination BY COLUMN NAME. When no explicit destination column list
            # is given, derive it from the source query's output column names — so
            # `SELECT alias, verse_no, bpm` loads into the dest columns of those names and leaves
            # the rest (e.g. an auto-generated `id`) to their defaults. Without a column list,
            # CSV COPY maps *positionally* into the table's full column order, which silently
            # routes the first SELECT value into the first table column (a common footgun).
            cols = list(dest_columns) if dest_columns else _query_columns(src_raw, source_sql)
            cols_clause = (" (" + ", ".join(_q(c) for c in cols) + ")") if cols else ""
            dst_copy_sql = f"COPY {dst_qual}{cols_clause} FROM STDIN (FORMAT csv)"

            src_cur = src_raw.cursor()
            dst_cur = dst_psyco.cursor()
            try:
                with src_cur.copy(src_copy_sql) as src_copy, dst_cur.copy(dst_copy_sql) as dst_copy:
                    for chunk in src_copy:
                        if chunk:
                            dst_copy.write(chunk)
                rows_written = max(dst_cur.rowcount or 0, 0)
            finally:
                src_cur.close()
                dst_cur.close()

        dst_psyco.commit()
    except Exception:
        try:
            dst_raw.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        dst_raw.close()

    return {
        "rows_written": rows_written,
        "detail": f"loaded {rows_written} row(s) into {dest_table} ({mode})",
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }
