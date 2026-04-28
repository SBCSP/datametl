from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.verification_run import VerificationRun


class VerificationTableStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"


class VerificationRunTable(Base):
    """Per-table verification result. `results` is a list[CheckResult dict] from the runner."""

    __tablename__ = "verification_run_tables"
    __table_args__ = (
        UniqueConstraint("run_id", "source_table", "dest_table", name="uq_verif_run_table"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_table: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(64), nullable=False, default="count_and_sample")
    status: Mapped[VerificationTableStatus] = mapped_column(
        Enum(VerificationTableStatus, name="verification_table_status"),
        nullable=False,
        default=VerificationTableStatus.pending,
    )
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    run: Mapped[VerificationRun] = relationship(VerificationRun)
