from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.schema_snapshot import SchemaSnapshot


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    dest_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schema_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Optional schema-scope filter. If both are set, the diff is restricted to those schemas
    # and matches table names by their bare name (so source.public.posts ↔ dest.legacy.posts
    # matches if both schemas have a "posts" table). If both are NULL, the comparison covers
    # every non-system schema in both snapshots.
    source_schema: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dest_schema: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    source_snapshot: Mapped[SchemaSnapshot] = relationship(SchemaSnapshot, foreign_keys=[source_snapshot_id])
    dest_snapshot: Mapped[SchemaSnapshot] = relationship(SchemaSnapshot, foreign_keys=[dest_snapshot_id])
