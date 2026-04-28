from app.connectors.base import Connector, ConnectionTestResult
from app.connectors.postgres import PostgresConnector

__all__ = ["Connector", "ConnectionTestResult", "PostgresConnector", "for_engine"]


def for_engine(engine: str, credentials: dict) -> Connector:
    """Factory: pick a connector implementation based on engine type."""
    match engine:
        case "postgres":
            return PostgresConnector(credentials)
        case _:
            raise ValueError(f"Unsupported engine: {engine}")
