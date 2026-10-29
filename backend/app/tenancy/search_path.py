"""Bind a DBAPI/SQLAlchemy connection to a tenant schema via search_path."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

from app.tenancy.names import assert_safe_schema_name


def set_search_path(connection: Connection | Any, schema_name: str, *, include_public: bool = True) -> None:
    """Set ``search_path`` (connection-scoped) so unqualified tables resolve to the tenant schema.

    Always keeps ``public`` after the tenant schema when ``include_public`` is True so
    control-plane tables (tenants, users, …) remain visible on the same connection.

    For an ORM ``Session`` use :func:`bind_session_search_path` instead: a Session releases
    its connection on every commit/rollback, so a one-shot ``SET`` stops applying after the
    first commit (and lingers on the pooled connection for whoever checks it out next).
    """
    name = assert_safe_schema_name(schema_name)
    # Identifiers validated; safe to interpolate.
    path = f"{name}, public" if include_public else name
    connection.execute(text(f"SET search_path TO {path}"))


def _search_path_sql(schema_name: str, *, local: bool) -> str:
    name = assert_safe_schema_name(schema_name)
    # Identifiers validated; safe to interpolate.
    return f"SET {'LOCAL ' if local else ''}search_path TO {name}, public"


def bind_session_search_path(
    session: Session, schema_name: str
) -> Callable[[Session, SessionTransaction, Connection], None]:
    """Keep ``search_path`` on the tenant schema for the whole life of an ORM ``Session``.

    ``SET LOCAL search_path`` is re-issued on every transaction the session begins (SQLAlchemy
    ``after_begin``), so it survives ``commit()``/``rollback()`` — which hand the connection
    back to the pool — and it resets automatically at transaction end, so a tenant's
    ``search_path`` never leaks into a pooled connection used by another request.

    Applies to the current transaction immediately (beginning one if needed). Returns the
    listener for tests.
    """
    sql = _search_path_sql(schema_name, local=True)

    def _apply(_session: Session, _txn: SessionTransaction, connection: Connection) -> None:
        connection.execute(text(sql))

    event.listen(session, "after_begin", _apply)
    # Begin (or join) the current transaction so the listener fires for it too.
    session.connection()
    return _apply
