from __future__ import annotations

import hashlib
import os
import time
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.connectors.base import ConnectionTestResult, Connector
from app.introspection import postgres as pg_introspect
from app.introspection.normalized import Schema
from app.scripts.runner import ROW_CAP, STATEMENT_TIMEOUT_S, StatementResult, cap_rows

_JSON_PRIMITIVES = (type(None), bool, int, float, str)


def _jsonable(value: Any) -> Any:
    """Coerce a DB cell to something the job-result JSON can carry.

    bytea → hex string; JSONB → passed through (already dict/list); everything exotic
    (datetime, Decimal, UUID, …) → str so the wire shape is predictable for the frontend.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, (*_JSON_PRIMITIVES, list, dict)):
        return value
    return str(value)

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

    def _engine(self) -> Engine:
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

    def run_statements(
        self,
        statements: list[str],
        row_cap: int = ROW_CAP,
        timeout_s: int = STATEMENT_TIMEOUT_S,
        read_only: bool = True,
    ) -> list[StatementResult]:
        results: list[StatementResult] = []
        errored = False
        eng = self._engine()
        with eng.connect() as conn:
            # The whole script runs in one transaction (atomic per connection). In read-only mode
            # we lock it (writes/DDL fail with "cannot execute ... in a read-only transaction")
            # and roll back at the end. In write mode we commit only if every statement
            # succeeds; any error rolls the whole script back. A statement_timeout caps runtime
            # either way.
            if read_only:
                conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET statement_timeout = '{int(timeout_s)}s'"))
            for index, stmt in enumerate(statements):
                started = time.perf_counter()
                try:
                    cursor = conn.execute(text(stmt))
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    if cursor.returns_rows:
                        fetched = cursor.fetchmany(row_cap + 1)
                        capped, truncated = cap_rows(list(fetched), row_cap)
                        rows = [[_jsonable(v) for v in row] for row in capped]
                        results.append(
                            StatementResult(
                                index=index, sql=stmt, kind="rows",
                                columns=list(cursor.keys()), rows=rows, row_count=len(rows),
                                truncated=truncated, duration_ms=duration_ms, error=None,
                            )
                        )
                    else:
                        affected = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                        results.append(
                            StatementResult(
                                index=index, sql=stmt, kind="command",
                                columns=[], rows=[], row_count=affected,
                                truncated=False, duration_ms=duration_ms, error=None,
                            )
                        )
                except SQLAlchemyError as e:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    results.append(
                        StatementResult(
                            index=index, sql=stmt, kind="error",
                            columns=[], rows=[], row_count=0, truncated=False,
                            duration_ms=duration_ms, error=str(e.__cause__ or e),
                        )
                    )
                    errored = True
                    break  # stop this connection's remaining statements on first error
            # Read-only always rolls back. Write mode commits only on a clean, complete run.
            if read_only or errored:
                conn.rollback()
            else:
                conn.commit()
        return results
