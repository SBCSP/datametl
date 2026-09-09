"""Bind a DBAPI/SQLAlchemy connection to a tenant schema via search_path."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.tenancy.names import assert_safe_schema_name


def set_search_path(connection: Connection | Any, schema_name: str, *, include_public: bool = True) -> None:
    """Set ``search_path`` so unqualified ORM tables resolve to the tenant schema.

    Always keeps ``public`` after the tenant schema when ``include_public`` is True so
    control-plane tables (tenants, users, …) remain visible on the same connection.
    Call at the start of a request or job once the tenant is known.

    ``connection`` may be a SQLAlchemy ``Connection`` or a sync session connection
    (``session.connection()``).
    """
    name = assert_safe_schema_name(schema_name)
    # Identifiers validated; safe to interpolate.
    path = f"{name}, public" if include_public else name
    connection.execute(text(f"SET search_path TO {path}"))
