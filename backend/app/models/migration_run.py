from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.comparison import Comparison


class MigrationRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MigrationRun(Base):
    """One execution attempt of a migration plan. Comparisons can have many runs (re-runs
    after fixing issues). Plan is persisted as JSONB for reproducibility."""

    __tablename__ = "migration_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comparisons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[MigrationRunStatus] = mapped_column(
        Enum(MigrationRunStatus, name="migration_run_status"),
        nullable=False,
        default=MigrationRunStatus.pending,
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    comparison: Mapped[Comparison] = relationship(Comparison)
