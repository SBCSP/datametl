from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ScheduledScript(Base):
    """A cron schedule that runs a saved SQL script against one or more connections.

    Decoupled from the manual /scripts run path: the worker's per-minute dispatcher finds
    enabled rows whose `next_run_at` is due, fires `run_scheduled_script`, and advances
    `next_run_at` via croniter in the schedule's `timezone`. `connection_ids` is a JSONB array
    of connection-uuid strings (chosen at schedule time, like the manual runner)."""

    __tablename__ = "scheduled_scripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    script_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sql_scripts.id", ondelete="CASCADE"), nullable=False
    )
    # List of connection-uuid strings to fan out to.
    connection_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cron: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    allow_writes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScheduledRun(Base):
    """History of one firing of a ScheduledScript. `summary` is a compact JSONB array of
    per-connection results — {connection_name, ok, error, row_total} — never the full result
    rows, so history stays small even for chatty queries."""

    __tablename__ = "scheduled_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_scripts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
