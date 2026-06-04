from app.connectors.base import Connector, ConnectionTestResult
from app.connectors.mysql import MySQLConnector
from app.connectors.postgres import PostgresConnector

__all__ = ["Connector", "ConnectionTestResult", "PostgresConnector", "MySQLConnector", "for_engine"]


def for_engine(engine: str, credentials: dict) -> Connector:
    """Factory: pick a connector implementation based on engine type."""
    match engine:
        case "postgres":
            return PostgresConnector(credentials)
        case "mysql":
            return MySQLConnector(credentials)
        case _:
            raise ValueError(f"Unsupported engine: {engine}")
