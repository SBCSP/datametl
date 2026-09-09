"""Dual migration strategy: public control (alembic main) + per-tenant template runner.

Public / control
  - Alembic revisions in ``backend/alembic/versions`` continue to run against the
    database with default search_path (public). Revision ``0019_public_control_plane``
    creates control tables with explicit ``schema="public"``.

Tenant template
  - Existing revisions ``0001``-``0018`` describe the historical single-tenant schema.
    That shape is the **tenant template baseline** (connections, Mel, mappings, ...).
  - ``upgrade_tenant_schema(schema_name)`` brings a given schema up to
    ``TENANT_TEMPLATE_REVISION`` by creating missing tenant tables (checkfirst) and
    stamping ``{schema}.alembic_version``.
  - Future tenant-only DDL should either (a) land as new alembic revisions after a
    dedicated tenant branch, or (b) extend this runner — see docs/TENANT_SCHEMA.md.
  - Do **not** run control revisions inside a tenant schema.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.tenancy.names import assert_safe_schema_name
from app.tenancy.tables import VERSION_TABLE_NAME, clone_tenant_metadata

log = logging.getLogger("datametl.tenancy.migrate")

# Last revision that only touches tenant-scoped tables (pre control-plane).
TENANT_TEMPLATE_REVISION = "0018_chat_session_tool_cards"


def _conn(engine_or_conn: Engine | Connection) -> tuple[Connection, bool]:
    """Return (connection, should_close)."""
    if isinstance(engine_or_conn, Engine):
        return engine_or_conn.connect(), True
    return engine_or_conn, False


def _ensure_version_table(connection: Connection, schema_name: str) -> None:
    connection.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS "{schema_name}".{VERSION_TABLE_NAME} ('
            "version_num VARCHAR(32) NOT NULL PRIMARY KEY"
            ")"
        )
    )


def get_tenant_revision(connection: Connection, schema_name: str) -> str | None:
    name = assert_safe_schema_name(schema_name)
    exists = connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :s AND table_name = :t"
        ),
        {"s": name, "t": VERSION_TABLE_NAME},
    ).scalar()
    if not exists:
        return None
    return connection.execute(
        text(f'SELECT version_num FROM "{name}".{VERSION_TABLE_NAME} LIMIT 1')
    ).scalar()


def stamp_tenant_revision(connection: Connection, schema_name: str, revision: str) -> None:
    name = assert_safe_schema_name(schema_name)
    _ensure_version_table(connection, name)
    connection.execute(text(f'DELETE FROM "{name}".{VERSION_TABLE_NAME}'))
    connection.execute(
        text(f'INSERT INTO "{name}".{VERSION_TABLE_NAME} (version_num) VALUES (:v)'),
        {"v": revision},
    )


def upgrade_tenant_schema(
    engine_or_conn: Engine | Connection | Any,
    schema_name: str,
    *,
    revision: str = TENANT_TEMPLATE_REVISION,
) -> str:
    """Create/upgrade tenant tables in ``schema_name`` up to the template revision.

    Pragmatic v1: ``create_all(checkfirst=True)`` from the ORM tenant metadata, then
    stamp ``alembic_version``. This avoids replaying 0001-0018 DDL (which assumed
    public) inside a new schema. Returns the stamped revision id.
    """
    name = assert_safe_schema_name(schema_name)
    conn, owns = _conn(engine_or_conn)
    try:
        with conn.begin():
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))
            meta = clone_tenant_metadata(name)
            meta.create_all(bind=conn, checkfirst=True)
            stamp_tenant_revision(conn, name, revision)
            log.info("tenant schema %s upgraded/stamped to %s", name, revision)
            return revision
    finally:
        if owns:
            conn.close()
