"""MySQL connector — self-contained, mirrors PostgresConnector but never imports/edits it.

Connection + introspection go through a SQLAlchemy engine (`mysql+pymysql://`). Statement
execution drives the raw pymysql connection directly so we get exact transaction control:
`START TRANSACTION READ ONLY` for the read-only path, plain `START TRANSACTION` for writes,
commit only on a clean write run, roll back otherwise.
"""
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
from app.introspection import mysql as my_introspect
from app.introspection.normalized import Schema
from app.scripts.runner import ROW_CAP, STATEMENT_TIMEOUT_S, StatementResult, cap_rows

_JSON_PRIMITIVES = (type(None), bool, int, float, str)
_CERT_DIR = "/tmp/datametl-certs"


def _jsonable(value: Any) -> Any:
    """Coerce a DB cell to JSON-carriable form (mirrors the Postgres connector)."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, (*_JSON_PRIMITIVES, list, dict)):
        return value
    return str(value)


def _materialize_root_cert(pem: str | None) -> str | None:
    """Write a CA PEM to a stable content-hashed path (same approach as the PG connector)."""
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


def _build_dsn(creds: dict[str, Any]) -> str:
    user = quote_plus(str(creds["user"]))
    password = quote_plus(str(creds["password"]))
    host = creds["host"]
    port = int(creds.get("port", 3306))
    database = creds["database"]
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"


def _ssl_connect_args(creds: dict[str, Any]) -> dict[str, Any]:
    """Map our generic sslmode/sslrootcert to pymysql TLS connect args.

    "" (unset) → let pymysql/server negotiate; "disabled" → force plaintext;
    "required" → encrypt without cert verification; "verify-ca"/"verify-identity" → verify
    against the supplied CA PEM (and hostname for verify-identity).
    """
    mode = (creds.get("sslmode") or "").strip().lower()
    if mode in ("", "prefer"):
        return {}
    if mode in ("disabled", "disable"):
        return {"ssl_disabled": True}
    if mode in ("verify-ca", "verify_ca", "verify-identity", "verify_identity"):
        args: dict[str, Any] = {"ssl_verify_cert": True,
                                "ssl_verify_identity": mode in ("verify-identity", "verify_identity")}
        if ca := _materialize_root_cert(creds.get("sslrootcert")):
            args["ssl_ca"] = ca
        return args
    # "required" (and any other truthy mode): encrypt, don't verify.
    return {"ssl": {}}


class MySQLConnector(Connector):
    engine = "mysql"

    def _engine(self) -> Engine:
        connect_args: dict[str, Any] = {"connect_timeout": 5, **_ssl_connect_args(self.credentials)}
        return create_engine(_build_dsn(self.credentials), pool_pre_ping=True, connect_args=connect_args)

    def test_connection(self) -> ConnectionTestResult:
        try:
            eng = self._engine()
            with eng.connect() as conn:
                version = conn.execute(text("SELECT VERSION()")).scalar_one()
            return ConnectionTestResult(ok=True, detail=f"MySQL {version}")
        except SQLAlchemyError as e:
            return ConnectionTestResult(ok=False, detail=str(e.__cause__ or e))
        except Exception as e:  # noqa: BLE001 — surface a sanitized message, never the DSN
            return ConnectionTestResult(ok=False, detail=str(e))

    def introspect(self) -> Schema:
        return my_introspect.introspect(self._engine())

    def run_statements(
        self,
        statements: list[str],
        row_cap: int = ROW_CAP,
        timeout_s: int = STATEMENT_TIMEOUT_S,
        read_only: bool = True,
    ) -> list[StatementResult]:
        results: list[StatementResult] = []
        errored = False
        raw = self._engine().raw_connection()
        try:
            dbapi = raw.driver_connection  # pymysql.Connection
            dbapi.autocommit(False)
            cur = dbapi.cursor()
            # Cap SELECT runtime, then open the transaction in the right access mode.
            cur.execute(f"SET SESSION max_execution_time = {int(timeout_s) * 1000}")
            cur.execute("START TRANSACTION READ ONLY" if read_only else "START TRANSACTION")
            for index, stmt in enumerate(statements):
                started = time.perf_counter()
                try:
                    cur.execute(stmt)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    if cur.description:
                        fetched = cur.fetchmany(row_cap + 1)
                        capped, truncated = cap_rows(list(fetched), row_cap)
                        rows = [[_jsonable(v) for v in row] for row in capped]
                        results.append(StatementResult(
                            index=index, sql=stmt, kind="rows",
                            columns=[d[0] for d in cur.description], rows=rows, row_count=len(rows),
                            truncated=truncated, duration_ms=duration_ms, error=None,
                        ))
                    else:
                        affected = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                        results.append(StatementResult(
                            index=index, sql=stmt, kind="command",
                            columns=[], rows=[], row_count=affected,
                            truncated=False, duration_ms=duration_ms, error=None,
                        ))
                except Exception as e:  # noqa: BLE001 — capture per statement, don't raise
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    msg = e.args[1] if getattr(e, "args", None) and len(e.args) > 1 else str(e)
                    results.append(StatementResult(
                        index=index, sql=stmt, kind="error",
                        columns=[], rows=[], row_count=0, truncated=False,
                        duration_ms=duration_ms, error=str(msg),
                    ))
                    errored = True
                    break
            if read_only or errored:
                dbapi.rollback()
            else:
                dbapi.commit()
        finally:
            raw.close()
        return results
