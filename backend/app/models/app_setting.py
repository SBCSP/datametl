from __future__ import annotations

from datetime import datetime

from sqlalchemy import LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AppSetting(Base):
    """A small key-value store for persisted, encrypted app settings (e.g. the Anthropic API
    key). Values are Fernet-encrypted JSON blobs — never stored or returned in plaintext."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
