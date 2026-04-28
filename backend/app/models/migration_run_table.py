from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.migration_run import MigrationRun


class TableRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class ConflictMode(str, enum.Enum):
    truncate = "truncate"
    append = "append"
    abort = "abort"


class MigrationRunTable(Base):
    """One row per (run, table) — captures per-table progress, metrics, verification results."""

    __tablename__ = "migration_run_tables"
    __table_args__ = (
        UniqueConstraint("run_id", "source_table", "dest_table", name="uq_run_table"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("migration_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_table: Mapped[str] = mapped_column(String(255), nullable=False)
    conflict_mode: Mapped[ConflictMode] = mapped_column(
        Enum(ConflictMode, name="migration_conflict_mode"), nullable=False, default=ConflictMode.truncate
    )
    status: Mapped[TableRunStatus] = mapped_column(
        Enum(TableRunStatus, name="migration_table_status"), nullable=False, default=TableRunStatus.pending
    )
    rows_read: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rows_written: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    run: Mapped[MigrationRun] = relationship(MigrationRun)
