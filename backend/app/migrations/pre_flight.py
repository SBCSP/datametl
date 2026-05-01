"""Pre-flight: read-only checks that surface issues *before* the migration writes anything.

Findings are categorized so the UI can render them: `error` blocks the run, `warning`
informs but doesn't block, `info` is just FYI (e.g. how many rows would be truncated).

The pre-flight uses live connections on both sides — it's the first thing that proves
"yes this plan can actually run as configured."

Performance discipline: pre-flight runs as a synchronous HTTP request (no arq), so the
UI is blocked until it returns. Every check here MUST be cheap. Specifically:
  - No `count(*)` against user tables — use `pg_class.reltuples` for size estimates.
  - Batch metadata queries instead of N round-trips per included table.
  - Any per-table scan (orphan check) gates itself on table size + a wall-clock budget
    + a per-query statement_timeout, and emits a summary finding for the skips.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text

from app.connectors.postgres import PostgresConnector
from app.crypto import vault
from app.migrations.planner import MigrationPlan
from app.models.comparison import Comparison
from app.models.connection import Connection
from app.models.mapping import Mapping
from app.models.schema_snapshot import SchemaSnapshot

log = logging.getLogger("datametl.preflight")

# Orphan scan limits — tuned so pre-flight stays under ~30s on a 400-table Supabase DB.
# Crossing any of these turns the per-FK scan into a "skipped, here's why" finding rather
# than letting it hang the UI.
_ORPHAN_SCAN_TOTAL_BUDGET_S = 20.0   # wall-clock cap across the whole orphan check
_ORPHAN_SCAN_PER_FK_TIMEOUT_MS = 2000  # per-query statement_timeout
_ORPHAN_SCAN_MAX_TABLE_ROWS = 500_000  # skip child tables bigger than this (reltuples)

Severity = Literal["error", "warning", "info"]


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    target: str | None = None  # e.g. "table:public.posts"

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "message": self.message, "target": self.target}


@dataclass
class PreFlightResult:
    findings: list[Finding]
    can_run: bool
    would_truncate_counts: dict[str, int]  # dest_table → estimated row count

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "can_run": self.can_run,
            "would_truncate_counts": self.would_truncate_counts,
        }


def run_preflight(
    db,
    *,
    plan: MigrationPlan,
    comparison: Comparison,
) -> PreFlightResult:
    """Execute every pre-flight check. Returns findings + a derived can_run flag.

    Caller is responsible for writing nothing when can_run is False.
    """
    findings: list[Finding] = []
    would_truncate: dict[str, int] = {}

    # Resolve source + dest connections
    src_snap = db.get(SchemaSnapshot, comparison.source_snapshot_id)
    dst_snap = db.get(SchemaSnapshot, comparison.dest_snapshot_id)
    if src_snap is None or dst_snap is None:
        findings.append(Finding("error", "preflight.snapshot_missing", "Comparison references missing snapshot(s)"))
        return PreFlightResult(findings, can_run=False, would_truncate_counts={})

    src_conn = db.get(Connection, src_snap.connection_id)
    dst_conn = db.get(Connection, dst_snap.connection_id)
    if src_conn is None or dst_conn is None:
        findings.append(Finding("error", "preflight.connection_missing", "Snapshot references missing connection(s)"))
        return PreFlightResult(findings, can_run=False, would_truncate_counts={})

    # Same-connection guard: refuse to migrate a database into itself (would self-corrupt under TRUNCATE).
    if src_conn.id == dst_conn.id:
        findings.append(
            Finding(
                "error", "preflight.same_connection",
                "Source and destination connections are the same — refusing to migrate a database into itself.",
            )
        )
        return PreFlightResult(findings, can_run=False, would_truncate_counts={})

    if not plan.included:
        findings.append(
            Finding("warning", "preflight.no_tables", "No tables selected for migration — nothing to do.")
        )
        # Still surface skipped-table DDL via plan.skipped; not blocking.

    # Live checks
    src_creds = vault.decrypt(src_conn.encrypted_credentials)
    dst_creds = vault.decrypt(dst_conn.encrypted_credentials)
    src_engine = PostgresConnector(src_creds)._engine()
    dst_engine = PostgresConnector(dst_creds)._engine()

    try:
        with src_engine.connect() as src, dst_engine.connect() as dst:
            for pt in plan.included:
                _check_table(
                    src, dst,
                    source_table=pt.source_table,
                    dest_table=pt.dest_table,
                    conflict_mode=pt.conflict_mode.value,
                    findings=findings,
                    would_truncate=would_truncate,
                )

            _check_mapping_coverage(
                db,
                comparison_id=comparison.id,
                included_tables=[(pt.source_table, pt.dest_table) for pt in plan.included],
                findings=findings,
            )

            # New audits — proactively surface the things that bite people on RDS.
            _check_dest_ownership(
                dst,
                included_tables=[pt.dest_table for pt in plan.included],
                findings=findings,
            )
            _check_source_orphans(
                src,
                included_source_tables=[pt.source_table for pt in plan.included],
                findings=findings,
            )

    except Exception as e:  # noqa: BLE001
        log.exception("preflight: connection-level failure")
        findings.append(Finding("error", "preflight.connect_failed", str(e)))

    has_error = any(f.severity == "error" for f in findings)
    return PreFlightResult(findings=findings, can_run=not has_error, would_truncate_counts=would_truncate)


def _split_qn(qn: str) -> tuple[str, str]:
    """`public.posts` → ('public', 'posts'). Bare names default to public."""
    if "." in qn:
        s, _, t = qn.partition(".")
        return s, t
    return "public", qn


def _check_table(
    src,
    dst,
    *,
    source_table: str,
    dest_table: str,
    conflict_mode: str,
    findings: list[Finding],
    would_truncate: dict[str, int],
) -> None:
    src_schema, src_name = _split_qn(source_table)
    dst_schema, dst_name = _split_qn(dest_table)

    log.info("preflight: checking %s → %s (mode=%s)", source_table, dest_table, conflict_mode)

    # Source must be readable.
    src_exists = bool(
        src.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": src_schema, "t": src_name},
        ).first()
    )
    if not src_exists:
        findings.append(
            Finding(
                "error", "preflight.source_table_missing",
                f"Source table {source_table} not found (was the source schema introspected since this comparison?).",
                target=f"table:{source_table}",
            )
        )
        return

    # Destination must exist (v1 doesn't create).
    dst_exists = bool(
        dst.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": dst_schema, "t": dst_name},
        ).first()
    )
    if not dst_exists:
        findings.append(
            Finding(
                "error", "preflight.dest_table_missing",
                f"Destination table {dest_table} does not exist. Create it first (Phase 1 surfaces a DDL preview).",
                target=f"table:{dest_table}",
            )
        )
        return

    # Cheap row-count estimate from pg_class.reltuples. Exact counts on huge RDS tables
    # (full scans!) used to dominate pre-flight runtime — this brings it back to near-zero.
    estimated_rows = int(
        dst.execute(
            text(
                """
                SELECT COALESCE(c.reltuples, 0)::bigint
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :s AND c.relname = :t
                """
            ),
            {"s": dst_schema, "t": dst_name},
        ).scalar_one_or_none()
        or 0
    )

    if conflict_mode == "abort":
        # Need a definitive yes/no, not an estimate. EXISTS stops at the first row — instant
        # on indexed tables and bounded by a single seq-scan otherwise.
        is_non_empty = bool(
            dst.execute(
                text(f"SELECT EXISTS (SELECT 1 FROM {_q(dst_schema)}.{_q(dst_name)} LIMIT 1)")  # noqa: S608
            ).scalar_one()
        )
        if is_non_empty:
            findings.append(
                Finding(
                    "error", "preflight.dest_not_empty",
                    f"Destination {dest_table} has data and conflict_mode is 'abort'.",
                    target=f"table:{dest_table}",
                )
            )
    elif conflict_mode == "truncate" and estimated_rows > 0:
        findings.append(
            Finding(
                "warning", "preflight.will_truncate",
                f"Destination {dest_table} will be TRUNCATEd (~{estimated_rows:,} rows lost).",
                target=f"table:{dest_table}",
            )
        )
        would_truncate[dest_table] = estimated_rows
    elif conflict_mode == "append" and estimated_rows > 0:
        findings.append(
            Finding(
                "info", "preflight.will_append",
                f"Destination {dest_table} has ~{estimated_rows:,} rows; new rows will be appended (PK collisions will fail mid-load).",
                target=f"table:{dest_table}",
            )
        )


def _check_mapping_coverage(
    db,
    *,
    comparison_id,
    included_tables: list[tuple[str, str]],
    findings: list[Finding],
) -> None:
    """Light sanity check: every included table has at least one non-skipped mapping row."""
    for src, dst in included_tables:
        n = (
            db.query(Mapping)
            .filter(
                Mapping.comparison_id == comparison_id,
                Mapping.source_table == src,
                Mapping.dest_table == dst,
                Mapping.skip.is_(False),
            )
            .count()
        )
        if n == 0:
            findings.append(
                Finding(
                    "error", "preflight.no_mapped_columns",
                    f"No mapped columns for {src} → {dst}. Configure mappings before running.",
                    target=f"table:{src}",
                )
            )


def _check_dest_ownership(
    dst,
    *,
    included_tables: list[str],
    findings: list[Finding],
) -> None:
    """For each included dest table, check whether the connecting user is the owner (or
    a member of the owner role). If not, ALTER TABLE DISABLE TRIGGER will fail at runtime
    — FK enforcement will fire during COPY and orphan rows will fail to load. We surface
    this as a warning per table so the user can fix it before the migration starts.

    Batched into a single query because RDS round-trip latency is ~30-50ms; doing this
    per-table on a 400-table Supabase database used to add ~15-20s to pre-flight on its own.
    """
    if not included_tables:
        return
    try:
        current_user = dst.execute(text("SELECT current_user")).scalar_one()
    except Exception:  # noqa: BLE001
        return

    # Build a VALUES list of (schema, name) pairs and join against pg_tables in one shot.
    pairs = [_split_qn(t) for t in included_tables]
    values_clause = ", ".join(f"(:s{i}, :t{i})" for i in range(len(pairs)))
    params: dict[str, str] = {}
    for i, (s, n) in enumerate(pairs):
        params[f"s{i}"] = s
        params[f"t{i}"] = n

    try:
        rows = dst.execute(
            text(
                f"""
                WITH wanted(schemaname, tablename) AS (VALUES {values_clause})
                SELECT
                    w.schemaname || '.' || w.tablename       AS qualified,
                    pt.tableowner                            AS owner,
                    COALESCE(pg_has_role(current_user, pt.tableowner, 'MEMBER'), false) AS is_member
                FROM wanted w
                LEFT JOIN pg_tables pt
                       ON pt.schemaname = w.schemaname AND pt.tablename = w.tablename
                WHERE pt.tableowner IS NOT NULL
                """  # noqa: S608 — VALUES placeholders are bound, identifiers are static
            ),
            params,
        ).all()
    except Exception as e:  # noqa: BLE001
        log.warning("preflight: ownership audit failed: %s", e)
        return

    for r in rows:
        if not r.is_member:
            findings.append(
                Finding(
                    "warning",
                    "preflight.not_table_owner",
                    (
                        f"Destination table {r.qualified} is owned by '{r.owner}', not by "
                        f"'{current_user}' (your migration user). DISABLE TRIGGER ALL will fail "
                        f"on this table; FK enforcement and user triggers will fire during COPY, "
                        f"which can cause cascading failures. Fix as the owner or rds_superuser: "
                        f"ALTER TABLE {r.qualified} OWNER TO {current_user};"
                    ),
                    target=f"table:{r.qualified}",
                )
            )


def _check_source_orphans(
    src,
    *,
    included_source_tables: list[str],
    findings: list[Finding],
) -> None:
    """Detect orphan rows on source — rows whose foreign key column points to a parent
    that doesn't exist. With FK enforcement on the destination during COPY, these rows
    cause the entire table's load to roll back. We surface counts so the user can either
    clean source or grant ownership (which lets us bypass FK enforcement).

    Cost discipline: the count(*) per FK is unbounded. On a real Supabase DB this used
    to hang pre-flight. We now:
      - skip FKs whose child table has > _ORPHAN_SCAN_MAX_TABLE_ROWS reltuples (huge tables);
      - put a per-query statement_timeout of _ORPHAN_SCAN_PER_FK_TIMEOUT_MS on each count;
      - cap the whole scan at _ORPHAN_SCAN_TOTAL_BUDGET_S wall-clock;
      - emit a single summary finding for everything we couldn't check, so the user knows.
    """
    included_set = set(included_source_tables)
    if not included_set:
        return

    started = time.monotonic()

    try:
        # Single query: pulls FK metadata + child reltuples so we can size-gate without
        # an extra round-trip per FK.
        fk_rows = src.execute(
            text(
                """
                SELECT
                  n_child.nspname  AS child_schema,
                  c_child.relname  AS child_table,
                  a_child.attname  AS child_col,
                  n_parent.nspname AS parent_schema,
                  c_parent.relname AS parent_table,
                  a_parent.attname AS parent_col,
                  con.conname      AS fk_name,
                  COALESCE(c_child.reltuples, 0)::bigint  AS child_reltuples
                FROM pg_constraint con
                JOIN pg_class c_child       ON c_child.oid  = con.conrelid
                JOIN pg_namespace n_child   ON n_child.oid  = c_child.relnamespace
                JOIN pg_class c_parent      ON c_parent.oid = con.confrelid
                JOIN pg_namespace n_parent  ON n_parent.oid = c_parent.relnamespace
                JOIN pg_attribute a_child   ON a_child.attrelid  = con.conrelid
                                            AND a_child.attnum   = con.conkey[1]
                JOIN pg_attribute a_parent  ON a_parent.attrelid = con.confrelid
                                            AND a_parent.attnum  = con.confkey[1]
                WHERE con.contype = 'f'
                  AND array_length(con.conkey, 1) = 1
                  AND n_child.nspname  NOT IN ('pg_catalog', 'information_schema')
                  AND n_parent.nspname NOT IN ('pg_catalog', 'information_schema')
                """
            )
        ).all()
    except Exception as e:  # noqa: BLE001
        log.warning("preflight: orphan scan failed to load FK list: %s", e)
        return

    # Filter to included child tables, then sort smallest-first so the cheap checks run
    # before we burn the wall-clock budget.
    candidates = [r for r in fk_rows if f"{r.child_schema}.{r.child_table}" in included_set]
    candidates.sort(key=lambda r: r.child_reltuples)

    # Per-query timeout for the entire orphan scan. Setting on the connection (not
    # SET LOCAL) — this is the last check in the pre-flight so we don't need to reset.
    try:
        src.execute(text(f"SET statement_timeout = {_ORPHAN_SCAN_PER_FK_TIMEOUT_MS}"))
    except Exception as e:  # noqa: BLE001
        log.debug("preflight: could not set statement_timeout for orphan scan: %s", e)

    skipped_too_big: list[str] = []
    skipped_timeout: list[str] = []
    skipped_budget: list[str] = []

    for r in candidates:
        child_qn = f"{r.child_schema}.{r.child_table}"
        fk_label = f"{child_qn}.{r.child_col} → {r.parent_schema}.{r.parent_table}.{r.parent_col}"

        # Wall-clock budget guard.
        if time.monotonic() - started > _ORPHAN_SCAN_TOTAL_BUDGET_S:
            skipped_budget.append(fk_label)
            continue

        # Size guard — skip huge tables; orphan-counting them would dominate pre-flight.
        if r.child_reltuples > _ORPHAN_SCAN_MAX_TABLE_ROWS:
            skipped_too_big.append(f"{fk_label} (~{int(r.child_reltuples):,} rows)")
            continue

        try:
            n = src.execute(
                text(
                    f"""
                    SELECT count(*)
                    FROM {_q(r.child_schema)}.{_q(r.child_table)} c
                    LEFT JOIN {_q(r.parent_schema)}.{_q(r.parent_table)} p
                      ON c.{_q(r.child_col)} = p.{_q(r.parent_col)}
                    WHERE c.{_q(r.child_col)} IS NOT NULL
                      AND p.{_q(r.parent_col)} IS NULL
                    """  # noqa: S608 — identifiers come from pg_catalog, not user input
                )
            ).scalar_one()
        except Exception as e:  # noqa: BLE001
            # statement_timeout fires here as psycopg.errors.QueryCanceled — treat any
            # exception the same: roll the connection back, record skip, keep going.
            try:
                src.rollback()
            except Exception:  # noqa: BLE001
                pass
            log.debug("preflight: orphan count failed/timed out for %s: %s", fk_label, e)
            skipped_timeout.append(fk_label)
            continue

        if n > 0:
            findings.append(
                Finding(
                    "warning",
                    "preflight.orphan_rows",
                    (
                        f"Source table {child_qn} has {n:,} orphan row(s) — column {r.child_col} "
                        f"references {r.parent_schema}.{r.parent_table}.{r.parent_col} that doesn't exist. "
                        f"With FK enforcement on (which happens when DISABLE TRIGGER fails), this table's "
                        f"COPY will fail and load 0 rows. Fix on source: "
                        f"DELETE FROM {child_qn} WHERE {r.child_col} IS NOT NULL "
                        f"AND {r.child_col} NOT IN (SELECT {r.parent_col} FROM {r.parent_schema}.{r.parent_table});"
                    ),
                    target=f"table:{child_qn}",
                )
            )

    # Surface a single summary finding for everything we didn't check, so the user knows
    # the orphan scan isn't a clean bill of health on those FKs.
    skipped_total = len(skipped_too_big) + len(skipped_timeout) + len(skipped_budget)
    if skipped_total:
        sample = (skipped_too_big + skipped_timeout + skipped_budget)[:8]
        more = skipped_total - len(sample)
        msg_parts = [f"Skipped orphan scan for {skipped_total} foreign key(s) to keep pre-flight responsive:"]
        if skipped_too_big:
            msg_parts.append(f"  - {len(skipped_too_big)} child table(s) larger than {_ORPHAN_SCAN_MAX_TABLE_ROWS:,} rows")
        if skipped_timeout:
            msg_parts.append(f"  - {len(skipped_timeout)} FK count(s) hit the per-query {_ORPHAN_SCAN_PER_FK_TIMEOUT_MS}ms timeout")
        if skipped_budget:
            msg_parts.append(f"  - {len(skipped_budget)} FK(s) skipped after the {_ORPHAN_SCAN_TOTAL_BUDGET_S:.0f}s wall-clock budget was used")
        msg_parts.append("Sample: " + "; ".join(sample) + (f"; +{more} more" if more > 0 else ""))
        msg_parts.append(
            "These won't block your migration if `session_replication_role = replica` "
            "is in effect on the destination (which suppresses FK enforcement during COPY)."
        )
        findings.append(
            Finding(
                "info",
                "preflight.orphan_scan_skipped",
                "\n".join(msg_parts),
                target=None,
            )
        )


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'
