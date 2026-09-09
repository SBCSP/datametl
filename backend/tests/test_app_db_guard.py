"""Unit tests for app metadata DB blocklist (Connections → DATABASE_URL)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "ENCRYPTION_KEY",
    "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=",
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.tenancy.app_db_guard import (
    APP_DB_BLOCK_MESSAGE,
    AppDatabaseBlockedError,
    assert_not_app_metadata_db,
    credentials_target_app_db,
    parse_app_db_target,
)

APP_URL = "postgresql+psycopg://meta:secret@db.internal:5432/datametl"


def _creds(**overrides: object) -> dict:
    base: dict = {
        "host": "db.internal",
        "port": 5432,
        "database": "datametl",
        "user": "u",
        "password": "p",
    }
    base.update(overrides)
    return base


def test_parse_app_db_target() -> None:
    host, database = parse_app_db_target(APP_URL)
    assert host == "db.internal"
    assert database == "datametl"


def test_exact_host_and_database_blocked() -> None:
    assert credentials_target_app_db(_creds(), database_url=APP_URL) is True


def test_different_database_allowed() -> None:
    assert (
        credentials_target_app_db(_creds(database="customer"), database_url=APP_URL) is False
    )


def test_different_host_allowed() -> None:
    assert (
        credentials_target_app_db(_creds(host="source.example.com"), database_url=APP_URL)
        is False
    )


def test_host_match_is_case_insensitive() -> None:
    assert credentials_target_app_db(_creds(host="DB.Internal"), database_url=APP_URL) is True


def test_database_match_is_case_insensitive() -> None:
    assert credentials_target_app_db(_creds(database="DataMETL"), database_url=APP_URL) is True


@pytest.mark.parametrize(
    "app_host,cand_host",
    [
        ("localhost", "127.0.0.1"),
        ("127.0.0.1", "localhost"),
        ("localhost", "::1"),
        ("[::1]", "127.0.0.1"),  # IPv6 must be bracketed in URLs
    ],
)
def test_loopback_aliases_match(app_host: str, cand_host: str) -> None:
    url = f"postgresql+psycopg://u:p@{app_host}:5432/datametl"
    assert credentials_target_app_db(_creds(host=cand_host), database_url=url) is True


def test_loopback_same_host_different_db_allowed() -> None:
    url = "postgresql+psycopg://u:p@localhost:5432/datametl"
    assert (
        credentials_target_app_db(_creds(host="127.0.0.1", database="other"), database_url=url)
        is False
    )


def test_sqlalchemy_url_host_db_comparison() -> None:
    """Credential fields round-trip through make_url and still match app URL host/db."""
    # Password with reserved chars exercises quote_plus + make_url path.
    assert (
        credentials_target_app_db(
            _creds(password="p@ss:word/!"),
            database_url=APP_URL,
        )
        is True
    )


def test_assert_raises_for_postgres() -> None:
    with pytest.raises(AppDatabaseBlockedError) as ei:
        assert_not_app_metadata_db(
            engine="postgres",
            credentials=_creds(),
            database_url=APP_URL,
        )
    assert str(ei.value) == APP_DB_BLOCK_MESSAGE
    assert "application metadata database" in str(ei.value)


def test_assert_skips_non_postgres_engines() -> None:
    # Same host/db as app URL but mysql — not the app metadata Postgres.
    assert_not_app_metadata_db(
        engine="mysql",
        credentials=_creds(),
        database_url=APP_URL,
    )
    assert_not_app_metadata_db(
        engine="mssql",
        credentials=_creds(),
        database_url=APP_URL,
    )


def test_assert_uses_settings_database_url_by_default() -> None:
    # conftest / env sets DATABASE_URL → localhost/test
    with pytest.raises(AppDatabaseBlockedError):
        assert_not_app_metadata_db(
            engine="postgres",
            credentials={
                "host": "127.0.0.1",
                "port": 5432,
                "database": "test",
                "user": "test",
                "password": "test",
            },
        )


def test_port_mismatch_still_blocked_when_host_and_db_match() -> None:
    # Port is not part of the match key — same host+db is enough (app may listen
    # on 5432 while a Connection form defaults differently).
    assert (
        credentials_target_app_db(_creds(port=15432), database_url=APP_URL) is True
    )
