from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Tap(Base):
    """A configured REST/JSON API data source ("Tap" plugin). Fetches JSON from an endpoint and
    lands each record as a JSONB row into one or more destination connections. The secret-bearing
    request config (headers / query params / body — which often carry API keys/tokens) is stored
    Fernet-encrypted, mirroring Connection.encrypted_credentials."""

    __tablename__ = "taps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False, server_default="GET", default="GET")
    # Dot path to the records array within the response (e.g. "data.items"); empty = use root.
    records_path: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", default="")
    dest_connection_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    dest_table: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", default="")
    write_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="append", default="append")
    # Encrypted JSON: {"headers": {...}, "query_params": {...}, "body": str|null}
    encrypted_config: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TapRun(Base):
    """One fetch of a Tap. `sample` holds the first few records (so the UI can show the structure,
    incl. when there's no destination); `summary` is a compact per-destination result."""

    __tablename__ = "tap_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("taps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
