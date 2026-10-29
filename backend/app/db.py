from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: session bound to the tenant ``search_path`` when context is set.

    Bound per transaction (not per connection) so it survives commit() — see
    ``bind_session_search_path``.
    """
    db = SessionLocal()
    try:
        from app.tenancy.context import get_tenant_context
        from app.tenancy.search_path import bind_session_search_path

        ctx = get_tenant_context()
        if ctx is not None:
            bind_session_search_path(db, ctx.schema_name)
        yield db
    finally:
        db.close()
