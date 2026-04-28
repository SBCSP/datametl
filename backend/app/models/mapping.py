from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.comparison import Comparison


class Mapping(Base):
    __tablename__ = "mappings"
    __table_args__ = (
        UniqueConstraint("comparison_id", "source_table", "source_column", name="uq_mapping_per_source_col"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comparisons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_table: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_column: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(255), nullable=False)
    default_dest_type: Mapped[str] = mapped_column(String(255), nullable=False)
    override_dest_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_lossy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    comparison: Mapped[Comparison] = relationship(Comparison)

    @property
    def effective_dest_type(self) -> str:
        return self.override_dest_type or self.default_dest_type
