from __future__ import annotations

import hashlib
import os
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.connectors.base import ConnectionTestResult, Connector
from app.introspection import postgres as pg_introspect
from app.introspection.normalized import Schema

# Where to materialize PEMs that come in via the API. Inside the container, /tmp is fine.
# Cert contents are public root CAs (not secret) so the only requirement is stable paths.
_CERT_DIR = "/tmp/datametl-certs"


def _build_dsn(creds: dict[str, Any]) -> str:
    """Assemble a SQLAlchemy URL from a credential dict.

    Required keys: host, port, database, user, password.
    Optional: sslmode, sslrootcert (PEM contents — handled separately via connect_args).
    """
    user = quote_plus(str(creds["user"]))
    password = quote_plus(str(creds["password"]))
    host = creds["host"]
    port = int(creds.get("port", 5432))
    database = creds["database"]
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    if sslmode := creds.get("sslmode"):
        dsn += f"?sslmode={sslmode}"
    return dsn


def _materialize_root_cert(pem: str | None) -> str | None:
    """Write a PEM root certificate to a stable path keyed by content hash.

    libpq needs a filesystem path for `sslrootcert`; we accept PEM as a string in the API
    and persist it here. Same content → same path, so repeated calls don't churn disk.
    """
    if not pem:
        return None
    pem = pem.strip() + "\n"
    digest = hashlib.sha256(pem.encode()).hexdigest()[:16]
    os.makedirs(_CERT_DIR, exist_ok=True)
    path = os.path.join(_CERT_DIR, f"{digest}.pem")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(pem)
        os.chmod(path, 0o600)
    return path


class PostgresConnector(Connector):
    engine = "postgres"

    def _engine(self):
        connect_args: dict[str, Any] = {"connect_timeout": 5}
        if cert_path := _materialize_root_cert(self.credentials.get("sslrootcert")):
            connect_args["sslrootcert"] = cert_path
        return create_engine(
            _build_dsn(self.credentials),
            pool_pre_ping=True,
            connect_args=connect_args,
        )

    def test_connection(self) -> ConnectionTestResult:
        try:
            eng = self._engine()
            with eng.connect() as conn:
                version = conn.execute(text("SELECT version()")).scalar_one()
            return ConnectionTestResult(ok=True, detail=str(version))
        except SQLAlchemyError as e:
            return ConnectionTestResult(ok=False, detail=str(e.__cause__ or e))
        except Exception as e:
            return ConnectionTestResult(ok=False, detail=str(e))

    def introspect(self) -> Schema:
        return pg_introspect.introspect(self._engine())
