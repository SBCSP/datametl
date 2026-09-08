from app.connectors.base import ConnectionTestResult, Connector
from app.connectors.mssql import MSSQLConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.postgres import PostgresConnector

__all__ = [
    "ConnectionTestResult",
    "Connector",
    "MSSQLConnector",
    "MySQLConnector",
    "PostgresConnector",
    "for_engine",
]


def for_engine(engine: str, credentials: dict) -> Connector:
    """Factory: pick a connector implementation based on engine type.

    Engine ids: `postgres`, `mysql`, `mssql` (SQL Server).
    """
    match engine:
        case "postgres":
            return PostgresConnector(credentials)
        case "mysql":
            return MySQLConnector(credentials)
        case "mssql":
            return MSSQLConnector(credentials)
        case _:
            raise ValueError(f"Unsupported engine: {engine}")
