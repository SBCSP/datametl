"""LogicalCopyStrategy — Postgres → Postgres streaming COPY.

For each table:
  1. (Optional) TRUNCATE destination
  2. Open `COPY (SELECT <select_exprs> FROM <src>) TO STDOUT (FORMAT BINARY)` on source
  3. Open `COPY <dst> (<dst_columns>) FROM STDIN (FORMAT BINARY)` on destination
  4. Stream chunks from source to destination via psycopg's copy iterator

Why binary COPY:
  * Skips text encoding/parsing — much faster, less CPU
  * Postgres validates types match exactly *after* the cast in the SELECT, which is what
    makes type-bridging work without an intermediate Python conversion

Notes:
  * Source query runs inside an implicit read-only transaction (`SET TRANSACTION READ ONLY`)
    to make absolutely sure no writes leak through this path.
  * Destination COPY runs inside a transaction; commit on success, rollback on error.
  * No explicit batch size — psycopg streams in network-sized chunks already.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text

from app.strategies.base import Strategy, TableMoveContext, TableMoveResult

log = logging.getLogger("datametl.strategy.logical_copy")


def _split_qn(qn: str) -> tuple[str, str]:
    if "." in qn:
        s, _, t = qn.partition(".")
        return s, t
    return "public", qn


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


class LogicalCopyStrategy(Strategy):
    name = "logical_copy"

    def run(self, src_engine, dst_engine, ctx: TableMoveContext) -> TableMoveResult:
        t0 = time.monotonic()
        src_schema, src_name = _split_qn(ctx.source_table)
        dst_schema, dst_name = _split_qn(ctx.dest_table)

        src_qual = f"{_q(src_schema)}.{_q(src_name)}"
        dst_qual = f"{_q(dst_schema)}.{_q(dst_name)}"

        select_clause = ", ".join(ctx.column_plan.select_exprs)
        dst_cols_clause = ", ".join(ctx.column_plan.dest_columns)

        src_query = f"COPY (SELECT {select_clause} FROM {src_qual}) TO STDOUT (FORMAT BINARY)"
        dst_query = f"COPY {dst_qual} ({dst_cols_clause}) FROM STDIN (FORMAT BINARY)"

        log.info("copy: %s → %s (%d cols)", ctx.source_table, ctx.dest_table, len(ctx.column_plan.dest_columns))
        log.debug("copy: src_query=%s", src_query)
        log.debug("copy: dst_query=%s", dst_query)

        rows_read = 0
        rows_written = 0
        detail = ""

        # Destination connection: we control the transaction so TRUNCATE + COPY commit atomically.
        dst_raw = dst_engine.raw_connection()
        try:
            dst_psyco = dst_raw.driver_connection  # psycopg.Connection
            dst_psyco.autocommit = False

            if ctx.conflict_mode == "truncate":
                with dst_psyco.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {dst_qual} RESTART IDENTITY")
            elif ctx.conflict_mode == "abort":
                with dst_psyco.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {dst_qual}")
                    n = cur.fetchone()[0]
                    if n > 0:
                        raise RuntimeError(
                            f"conflict_mode=abort but {ctx.dest_table} has {n:,} rows"
                        )
            # append: do nothing; rows go on top of what's there.

            # Source: stream out
            with src_engine.connect() as src_conn:
                # Force read-only at the transaction level.
                src_conn.execute(text("SET TRANSACTION READ ONLY"))
                src_raw = src_conn.connection.driver_connection  # psycopg.Connection

                with src_raw.cursor().copy(src_query) as src_copy:
                    with dst_psyco.cursor().copy(dst_query) as dst_copy:
                        for chunk in src_copy:
                            if chunk:
                                dst_copy.write(chunk)
                                # `chunk` is a memoryview/bytes — we don't get a per-row count
                                # from binary COPY out, but we can pull statusmessage / rowcount
                                # at the end for the destination side.

                    rows_written = dst_copy.rowcount or 0
                rows_read = src_copy.rowcount or rows_written  # fallback

            dst_psyco.commit()

        except Exception:
            dst_raw.rollback()
            raise
        finally:
            dst_raw.close()

        # Sequence parity touch-up: for any PK columns backed by a sequence, advance it past max(pk).
        # This prevents the next INSERT on the destination from colliding with migrated rows.
        try:
            seq_msgs = _refresh_sequences(dst_engine, dst_schema, dst_name)
            if seq_msgs:
                detail = "; ".join(seq_msgs)
        except Exception as e:  # noqa: BLE001 — not fatal; log and continue
            log.warning("copy: sequence refresh failed for %s: %s", ctx.dest_table, e)
            detail = f"sequence refresh failed: {e}"

        return TableMoveResult(
            rows_read=rows_read,
            rows_written=rows_written,
            duration_ms=int((time.monotonic() - t0) * 1000),
            detail=detail,
        )


def _refresh_sequences(dst_engine, schema: str, table: str) -> list[str]:
    """For every column on `schema.table` whose default uses a sequence, run setval to
    advance the sequence past the current max. Returns human-readable messages per column."""
    msgs: list[str] = []
    with dst_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name, pg_get_serial_sequence(:fqn, column_name) AS seq
                FROM information_schema.columns
                WHERE table_schema = :s AND table_name = :t
                """
            ),
            {"fqn": f"{schema}.{table}", "s": schema, "t": table},
        ).all()
        for r in rows:
            seq = r.seq
            if not seq:
                continue
            max_val = conn.execute(
                text(f'SELECT max({_q(r.column_name)}) FROM {_q(schema)}.{_q(table)}')  # noqa: S608
            ).scalar()
            if max_val is None:
                continue
            conn.execute(text(f"SELECT setval('{seq}', :v)"), {"v": max_val})
            msgs.append(f"{r.column_name}: setval({seq}, {max_val})")
    return msgs
