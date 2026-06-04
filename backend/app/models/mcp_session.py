from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class McpSession(Base):
    """Which connection is the live, read-only MCP target — at most one row at a time.

    Activating a connection replaces this row; deactivating deletes it. Persisted (not just
    in-memory) so the backend, worker, and MCP server all agree and it survives restarts.
    """

    __tablename__ = "mcp_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    activated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
