"""Which connection is the active read-only MCP target. At most one at a time."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.mcp_session import McpSession


def get_active_connection(db: Session) -> Connection | None:
    """The Connection currently activated for MCP, or None."""
    row = db.execute(select(McpSession)).scalars().first()
    if row is None:
        return None
    return db.get(Connection, row.connection_id)


def set_active(db: Session, connection_id: uuid.UUID) -> Connection:
    """Make `connection_id` the sole active MCP connection (replaces any existing)."""
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise ValueError("Connection not found")
    db.execute(delete(McpSession))  # one-at-a-time
    db.add(McpSession(connection_id=connection_id))
    db.commit()
    return conn


def clear_active(db: Session) -> None:
    db.execute(delete(McpSession))
    db.commit()
