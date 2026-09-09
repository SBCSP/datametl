"""Cutover helpers: move legacy public tenant tables into ``tenant_<uuidhex>`` via SET SCHEMA.

Safe to run only when:
  - Control-plane migration 0019 has been applied
  - Target schema exists and is empty of conflicting table names
  - App is quiesced (no writers)

See docs/TENANT_SCHEMA.md for the operator runbook.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.models.tenant_control import Tenant, TenantLicense
from app.tenancy.migrate import TENANT_TEMPLATE_REVISION, stamp_tenant_revision
from app.tenancy.names import assert_safe_schema_name, tenant_schema_name
from app.tenancy.tables import tenant_table_names

log = logging.getLogger("datametl.tenancy.cutover")

# Well-known id for the single legacy install tenant (stable across re-runs).
DEFAULT_CUTOVER_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def plan_set_schema_statements(
    schema_name: str,
    table_names: Iterable[str] | None = None,
) -> list[str]:
    """Return ``ALTER TABLE ... SET SCHEMA`` statements for cutover (dry-run friendly)."""
    name = assert_safe_schema_name(schema_name)
    tables = sorted(table_names if table_names is not None else tenant_table_names())
    return [f'ALTER TABLE public."{t}" SET SCHEMA "{name}"' for t in tables]


def ensure_default_tenant_row(db: Session, *, name: str = "Default") -> Tenant:
    """Idempotent control row for the legacy single-tenant cutover target."""
    tid = DEFAULT_CUTOVER_TENANT_ID
    schema_name = tenant_schema_name(tid)
    existing = db.get(Tenant, tid)
    if existing is not None:
        return existing
    tenant = Tenant(id=tid, kind="org", name=name, schema_name=schema_name)
    db.add(tenant)
    db.add(TenantLicense(tenant_id=tid, tier="community"))
    db.commit()
    db.refresh(tenant)
    return tenant


def _table_in_public(conn: Connection, table_name: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table_name},
        ).scalar()
    )


def _apply_set_schema(conn: Connection, schema_name: str, stmts: list[str]) -> None:
    name = assert_safe_schema_name(schema_name)
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))
    for sql in stmts:
        tname = sql.split('public."')[1].split('"')[0]
        if _table_in_public(conn, tname):
            conn.execute(text(sql))
            log.info("moved public.%s -> %s", tname, name)
    stamp_tenant_revision(conn, name, TENANT_TEMPLATE_REVISION)


def cutover_public_to_tenant(
    engine_or_session: Engine | Session | Connection,
    schema_name: str,
    *,
    dry_run: bool = True,
) -> list[str]:
    """Move public tenant tables into ``schema_name`` with SET SCHEMA.

    Defaults to dry_run=True (returns SQL only). Pass dry_run=False to execute.
    Creates the schema if needed; stamps tenant alembic_version after move.
    """
    name = assert_safe_schema_name(schema_name)
    stmts = plan_set_schema_statements(name)
    if dry_run:
        return stmts

    if isinstance(engine_or_session, Session):
        conn = engine_or_session.connection()
        _apply_set_schema(conn, name, stmts)
        engine_or_session.commit()
        return stmts

    if isinstance(engine_or_session, Engine):
        with engine_or_session.begin() as conn:
            _apply_set_schema(conn, name, stmts)
        return stmts

    conn = engine_or_session
    with conn.begin():
        _apply_set_schema(conn, name, stmts)
    return stmts
