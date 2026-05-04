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

        # Detect Postgres GENERATED columns on either side and exclude them from the COPY.
        # Postgres refuses to INSERT into a generated column ("Generated columns cannot be
        # used in COPY"); the dest computes them automatically from the other columns.
        # We also skip any generated column on the source SELECT so the column counts line
        # up between the two halves of the COPY.
        gen_cols: set[str] = _generated_columns(src_engine, src_schema, src_name) | _generated_columns(
            dst_engine, dst_schema, dst_name
        )
        select_exprs = ctx.column_plan.select_exprs
        dest_columns = ctx.column_plan.dest_columns
        if gen_cols:
            kept_pairs = [
                (s, d) for s, d in zip(select_exprs, dest_columns)
                if _bare(d) not in gen_cols
            ]
            dropped = [d for d in dest_columns if _bare(d) in gen_cols]
            select_exprs = [s for s, _ in kept_pairs]
            dest_columns = [d for _, d in kept_pairs]
            if dropped:
                log.info("copy: %s skipping generated column(s) %s", ctx.dest_table, dropped)

        if not dest_columns:
            raise RuntimeError(
                f"All columns in {ctx.dest_table} are generated — nothing to write."
            )

        select_clause = ", ".join(select_exprs)
        dst_cols_clause = ", ".join(dest_columns)

        src_query = f"COPY (SELECT {select_clause} FROM {src_qual}) TO STDOUT (FORMAT BINARY)"
        dst_query = f"COPY {dst_qual} ({dst_cols_clause}) FROM STDIN (FORMAT BINARY)"

        log.info("copy: %s → %s (%d cols)", ctx.source_table, ctx.dest_table, len(dest_columns))
        log.debug("copy: src_query=%s", src_query)
        log.debug("copy: dst_query=%s", dst_query)

        rows_read = 0
        rows_written = 0
        detail = ""

        # Destination connection. We split the work into two phases:
        #
        #   Phase 1 (autocommit ON): housekeeping commands — SET statement_timeout,
        #     ALTER TABLE DISABLE TRIGGER. Each statement auto-commits independently, so
        #     a failed-permission ALTER TABLE doesn't poison the connection's transaction
        #     state for the COPY that follows. (This is the bug that produced the
        #     "current transaction is aborted" cascade on RDS — DISABLE TRIGGER failed,
        #     no rollback was issued, and every subsequent statement on the same
        #     connection got rejected.)
        #
        #   Phase 2 (autocommit OFF): TRUNCATE + COPY + ENABLE TRIGGER, all wrapped in
        #     one transaction so the load is atomic. If the COPY fails, the rollback
        #     restores both the data and the trigger state for THIS table.
        dst_raw = dst_engine.raw_connection()
        try:
            dst_psyco = dst_raw.driver_connection  # psycopg.Connection

            # Clear any pending transaction state from the connection (e.g. from a SET in
            # the engine "connect" event listener) so we can flip autocommit cleanly.
            try:
                dst_psyco.rollback()
            except Exception:  # noqa: BLE001
                pass
            dst_psyco.autocommit = True

            # --- Phase 1: setup, autocommit-style ---

            # Re-establish session_replication_role = replica on this connection. The
            # runner's connect-event listener also sets it (and now commits it), but we
            # belt-and-suspenders here because:
            #   1. autocommit mode means this SET survives any subsequent rollback;
            #   2. if a future change to the listener regresses, this keeps the load safe;
            #   3. the SHOW below proves the value at copy-time, so any future regression
            #      is one log line away from being self-diagnosed.
            # If this fails (no rds_replication / SUPERUSER) we fall through with a warning
            # and rely on `DISABLE TRIGGER ALL` (which itself usually fails on RDS, hence
            # the cascade we kept hitting before this fix landed).
            try:
                with dst_psyco.cursor() as cur:
                    cur.execute("SET session_replication_role = replica")
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "copy: SET session_replication_role = replica failed on %s: %s. "
                    "FK enforcement will be active during COPY — orphan rows will fail the load.",
                    ctx.dest_table, e,
                )

            try:
                with dst_psyco.cursor() as cur:
                    cur.execute("SHOW session_replication_role")
                    role = cur.fetchone()[0]
                log.info("copy: %s session_replication_role=%s at copy time", ctx.dest_table, role)
            except Exception:  # noqa: BLE001
                pass

            # Disable statement_timeout — large COPYs can take many minutes; Supabase's
            # 30-60s default would cancel them mid-stream. SET is session-level.
            try:
                with dst_psyco.cursor() as cur:
                    cur.execute("SET statement_timeout = 0")
            except Exception as e:  # noqa: BLE001
                log.warning("copy: SET statement_timeout failed on %s: %s", ctx.dest_table, e)

            # Disable triggers on the dest table for the duration of the load:
            #   * FK constraints are implemented as system triggers — disabling them lets
            #     us load without `rds_replication` (which most RDS users don't have).
            #   * User-defined triggers can reference columns the source row doesn't have;
            #     skipping them avoids shape-mismatch errors.
            # Requires table-owner privilege. If denied, the warning is logged and we
            # continue — FK errors during COPY become possible.
            triggers_disabled = False
            try:
                with dst_psyco.cursor() as cur:
                    cur.execute(f"ALTER TABLE {dst_qual} DISABLE TRIGGER ALL")
                triggers_disabled = True
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "copy: could not DISABLE TRIGGER ALL on %s (likely not table owner): %s. "
                    "FK + user triggers will fire during load.", ctx.dest_table, e,
                )

            # --- Phase 2: load, transactional ---
            dst_psyco.autocommit = False

            if ctx.conflict_mode == "truncate" and not ctx.skip_truncate:
                # CASCADE handles the case where other tables have FKs pointing at this one
                # (Postgres refuses TRUNCATE without CASCADE in that case).
                #
                # WARNING: this branch is the legacy fallback. The runner does an upfront
                # bulk TRUNCATE of every truncate-mode table in one statement and sets
                # `ctx.skip_truncate = True` for those — preferred because per-table
                # TRUNCATE … CASCADE here will silently wipe already-loaded children
                # whose parents the topo sort placed later than they should have been.
                # We only land here if the runner's bulk TRUNCATE itself failed (e.g.
                # permission), in which case the runner has already logged a warning.
                with dst_psyco.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {dst_qual} RESTART IDENTITY CASCADE")
            elif ctx.conflict_mode == "truncate" and ctx.skip_truncate:
                log.debug("copy: %s already truncated upfront — skipping per-table TRUNCATE", ctx.dest_table)
            elif ctx.conflict_mode == "abort":
                with dst_psyco.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {dst_qual}")
                    n = cur.fetchone()[0]
                    if n > 0:
                        raise RuntimeError(
                            f"conflict_mode=abort but {ctx.dest_table} has {n:,} rows"
                        )
            # append: do nothing; rows go on top of what's there.

            # Source: stream out. Keep separate cursor objects so we can read .rowcount AFTER
            # the COPY finishes — psycopg3's Copy object doesn't expose rowcount directly;
            # the parent cursor does.
            with src_engine.connect() as src_conn:
                # Force read-only at the transaction level.
                src_conn.execute(text("SET TRANSACTION READ ONLY"))
                # Disable statement_timeout on source — same reason as dest. Supabase's
                # default of 30s would cancel COPYs of large tables.
                src_conn.execute(text("SET statement_timeout = 0"))
                src_raw = src_conn.connection.driver_connection  # psycopg.Connection

                src_cur = src_raw.cursor()
                dst_cur = dst_psyco.cursor()
                try:
                    with src_cur.copy(src_query) as src_copy:
                        with dst_cur.copy(dst_query) as dst_copy:
                            for chunk in src_copy:
                                if chunk:
                                    dst_copy.write(chunk)
                    # Both copy contexts have closed at this point. Cursors still hold rowcount.
                    rows_written = max(dst_cur.rowcount or 0, 0)
                    rows_read = max(src_cur.rowcount or 0, rows_written)
                finally:
                    src_cur.close()
                    dst_cur.close()

            # Re-enable triggers BEFORE commit so the ENABLE is part of the same transaction
            # as the load. If anything failed earlier, the rollback path also re-enables them
            # (see the except/finally below).
            if triggers_disabled:
                with dst_psyco.cursor() as cur:
                    cur.execute(f"ALTER TABLE {dst_qual} ENABLE TRIGGER ALL")

            dst_psyco.commit()

        except Exception:
            # Rollback the Phase-2 transaction (undoes TRUNCATE + COPY + ENABLE TRIGGER if
            # they ran). The Phase-1 DISABLE TRIGGER was committed under autocommit, so
            # rolling back here does NOT restore triggers — we must re-enable explicitly on
            # a fresh connection. Otherwise we'd leave the table with triggers off, which
            # silently breaks FK enforcement and any user triggers for everyone using this DB.
            try:
                dst_raw.rollback()
            except Exception:  # noqa: BLE001
                pass
            if triggers_disabled:
                try:
                    with dst_engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {dst_qual} ENABLE TRIGGER ALL"))
                except Exception:  # noqa: BLE001
                    log.warning(
                        "copy: failed to re-enable triggers on %s after error — table may "
                        "be left with triggers DISABLED. Manual fix: ALTER TABLE %s ENABLE TRIGGER ALL;",
                        ctx.dest_table, ctx.dest_table,
                    )
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


def _bare(quoted: str) -> str:
    """`"col"` → `col`; handles doubled-quote escapes."""
    if quoted.startswith('"') and quoted.endswith('"'):
        return quoted[1:-1].replace('""', '"')
    return quoted


def _generated_columns(engine, schema: str, table: str) -> set[str]:
    """Return the names of GENERATED (ALWAYS) columns on the given table.

    Postgres has two flavors:
      * STORED:    `... GENERATED ALWAYS AS (expr) STORED`
      * IDENTITY:  `... GENERATED ALWAYS AS IDENTITY` (also can't be COPY'd into in some
                   modes, but `OVERRIDING SYSTEM VALUE` would help — we punt on this for
                   now and let the user opt-in via mapping if needed)

    We treat both as "skip on COPY" since either can break a binary INSERT.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT a.attname AS column_name
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = :s
                      AND c.relname = :t
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                      AND (a.attgenerated <> '' OR a.attidentity = 'a')
                    """
                ),
                {"s": schema, "t": table},
            ).all()
            return {r.column_name for r in rows}
    except Exception:  # noqa: BLE001
        # Defensive: if the lookup fails, return empty set; the COPY will surface any real
        # issue with a clear error message.
        return set()


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
