from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class SqlScript(Base):
    """A saved, reusable SQL script. Decoupled from connections — the connections to run it
    against are chosen at run time, so the same script can fan out across many databases."""

    __tablename__ = "sql_scripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Free-text notes about what the script does — purely informational.
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    run_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), nullable=False)
