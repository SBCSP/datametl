"""Refuse Mel/Connections that target the application metadata Postgres database.

Mel and MCP talk to customer data through Connection rows. Blocking create / test /
update when host+database match ``settings.database_url`` is enough to keep Mel from
reaching the app metadata DB (it cannot use a Connection that was never stored).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from sqlalchemy.engine.url import make_url

APP_DB_BLOCK_MESSAGE = (
    "Cannot connect to the application metadata database. "
    "Use a separate Postgres database for migration sources and destinations."
)

# Loopback aliases we treat as the same host so a Connection cannot slip past via
# localhost vs 127.0.0.1 / ::1. Prefer exact host string match first; alias fold is
# an additional check only for this small known set.
_LOOPBACK_ALIASES = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


class AppDatabaseBlockedError(ValueError):
    """Raised when credentials target the app metadata Postgres database."""

    def __init__(self, message: str = APP_DB_BLOCK_MESSAGE) -> None:
        super().__init__(message)


def _strip_ipv6_brackets(host: str) -> str:
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        return h[1:-1]
    return h


def _db_key(name: str | None) -> str:
    n = (name or "").strip()
    if n.startswith("/"):
        n = n[1:]
    # Postgres folds unquoted identifiers; compare case-insensitively.
    return n.casefold()


def parse_app_db_target(database_url: str) -> tuple[str, str]:
    """Return ``(host, database)`` from ``DATABASE_URL`` via SQLAlchemy URL parsing."""
    url = make_url(database_url)
    return (url.host or ""), (url.database or "")


def _hosts_match(a: str | None, b: str | None) -> bool:
    """Exact host string match (case-insensitive), or shared loopback alias."""
    a_raw = _strip_ipv6_brackets(a or "")
    b_raw = _strip_ipv6_brackets(b or "")
    if not a_raw or not b_raw:
        return False
    if a_raw.casefold() == b_raw.casefold():
        return True
    # Alias fold only when both sides are known loopbacks (localhost ↔ 127.0.0.1).
    return a_raw.casefold() in _LOOPBACK_ALIASES and b_raw.casefold() in _LOOPBACK_ALIASES


def _credentials_as_url_host_db(credentials: dict[str, Any]) -> tuple[str, str]:
    """Build a SQLAlchemy URL from credential fields and return host + database.

    Mirrors how the Postgres connector assembles DSNs so we compare the same
    host/db SQLAlchemy would see.
    """
    host = str(credentials.get("host") or "")
    port = int(credentials.get("port") or 5432)
    database = str(credentials.get("database") or "")
    user = quote_plus(str(credentials.get("user") or "x"))
    password = quote_plus(str(credentials.get("password") or "x"))
    # Host may be IPv6; SQLAlchemy accepts bracketed forms in the URL.
    host_for_url = host
    if ":" in host and not host.startswith("["):
        host_for_url = f"[{host}]"
    dsn = f"postgresql+psycopg://{user}:{password}@{host_for_url}:{port}/{database}"
    url = make_url(dsn)
    return (url.host or ""), (url.database or "")


def credentials_target_app_db(
    credentials: dict[str, Any],
    *,
    database_url: str,
) -> bool:
    """True when credential host + database name match the app metadata DB.

    Matching rules (any hit → blocked):
    1. Exact host string (case-insensitive) + database name from parsed
       ``settings.database_url`` / ``DATABASE_URL``.
    2. Same after loopback alias normalization (localhost ↔ 127.0.0.1 ↔ ::1).
    3. Same comparison using host/db from a SQLAlchemy URL built from the
       credential dict (parity with the Postgres connector DSN).
    """
    app_host, app_db = parse_app_db_target(database_url)
    if not _db_key(app_db):
        return False

    cand_host = str(credentials.get("host") or "")
    cand_db = str(credentials.get("database") or "")
    if not _db_key(cand_db):
        return False

    if _hosts_match(cand_host, app_host) and _db_key(cand_db) == _db_key(app_db):
        return True

    try:
        url_host, url_db = _credentials_as_url_host_db(credentials)
    except Exception:
        return False

    return _hosts_match(url_host, app_host) and _db_key(url_db) == _db_key(app_db)


def assert_not_app_metadata_db(
    *,
    engine: str,
    credentials: dict[str, Any],
    database_url: str | None = None,
) -> None:
    """Raise ``AppDatabaseBlockedError`` if a postgres Connection targets the app DB.

    Non-postgres engines are ignored (app metadata is always Postgres).
    """
    if (engine or "").lower() != "postgres":
        return
    if database_url is None:
        from app.config import settings

        database_url = settings.database_url
    if credentials_target_app_db(credentials, database_url=database_url):
        raise AppDatabaseBlockedError()
