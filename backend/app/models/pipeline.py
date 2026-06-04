from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Pipeline(Base):
    """An ordered, repeatable ETL job: a list of steps that run sequentially against one or
    more database connections. A pipeline owns its steps; runs are recorded separately."""

    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PipelineStep(Base):
    """One step in a pipeline. `step_type` selects the executor; `config` is a type-specific
    JSONB blob:

      sql:      {connection_id, script_id?|inline_sql?, allow_writes:bool}
      transfer: {source_connection_id, source_script_id?|source_sql?, dest_connection_id,
                 dest_table:"schema.table", dest_columns?:[...], mode:"truncate"|"append"}
    """

    __tablename__ = "pipeline_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", default="")
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "sql" | "transfer"
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PipelineRun(Base):
    """One execution of a pipeline. Status: pending|running|succeeded|failed."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PipelineRunStep(Base):
    """Per-step progress within a run. Status: pending|running|succeeded|failed|skipped.
    `summary` is a compact JSONB blob of what the step did (rows, statement results, detail)."""

    __tablename__ = "pipeline_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", default="")
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Snapshot of the step's config at run-creation time, so the run is self-contained and
    # immune to later edits of the pipeline.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
