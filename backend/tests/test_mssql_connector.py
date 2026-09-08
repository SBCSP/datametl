"""Focused unit tests for the SQL Server (mssql) connector DSN/builder helpers."""

from __future__ import annotations

import pytest

from app.connectors import for_engine
from app.connectors.mssql import MSSQLConnector, _build_dsn, _connect_args
from app.introspection.mssql import _normalize_mssql_type
from app.mapping.registry import default_dest_type


def test_for_engine_builds_mssql_connector():
    c = for_engine(
        "mssql",
        {"host": "db", "port": 1433, "database": "app", "user": "sa", "password": "x"},
    )
    assert isinstance(c, MSSQLConnector)
    assert c.engine == "mssql"


def test_build_dsn_quotes_special_chars():
    dsn = _build_dsn(
        {
            "host": "engine-mssql",
            "port": 1433,
            "database": "master",
            "user": "sa",
            "password": "P@ss:word/!",
        }
    )
    assert dsn.startswith("mssql+pymssql://")
    assert "@engine-mssql:1433/master" in dsn
    assert "P%40ss%3Aword%2F%21" in dsn


def test_connect_args_always_set_timeouts():
    args = _connect_args({"sslmode": "require"})
    assert args["login_timeout"] == 5
    assert args["timeout"] == 30


@pytest.mark.parametrize(
    "native,expected",
    [
        ("NVARCHAR(255)", "string"),
        ("varchar(50)", "string"),
        ("INT", "int32"),
        ("BIGINT", "int64"),
        ("SMALLINT", "int16"),
        ("BIT", "boolean"),
        ("UNIQUEIDENTIFIER", "uuid"),
        ("DATETIME2", "timestamp"),
        ("DATETIMEOFFSET", "timestamptz"),
        ("DECIMAL(18,2)", "decimal"),
        ("VARBINARY(MAX)", "binary"),
        ("rowversion", "binary"),
        ("GEOMETRY", "geometry"),
        ("weird_udt", "unknown"),
    ],
)
def test_normalize_mssql_type(native: str, expected: str) -> None:
    assert _normalize_mssql_type(native) == expected


def test_mapping_registry_mssql_dest():
    assert default_dest_type("postgres", "text", "string", "mssql") == "NVARCHAR(MAX)"
    assert default_dest_type("mssql", "NVARCHAR(100)", "string", "mssql") == "NVARCHAR(100)"
