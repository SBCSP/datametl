"""Pre-flight: read-only checks that surface issues *before* the migration writes anything.

Findings are categorized so the UI can render them: `error` blocks the run, `warning`
informs but doesn't block, `info` is just FYI (e.g. how many rows would be truncated).

The pre-flight uses live connections on both sides — it's the first thing that proves
"yes this plan can actually run as configured."
"""
from __future__ import annotations

import logging
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


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'
