from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: session with tenant ``search_path`` when context is set."""
    db = SessionLocal()
    try:
        from app.tenancy.context import get_tenant_context
        from app.tenancy.search_path import set_search_path

        ctx = get_tenant_context()
        if ctx is not None:
            set_search_path(db.connection(), ctx.schema_name)
        yield db
    finally:
        db.close()
