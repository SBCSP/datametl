"""SQL Server connector — self-contained, mirrors MySQLConnector.

Connection + introspection use SQLAlchemy (`mssql+pymssql://`). Statement execution
drives the raw pymssql connection for explicit BEGIN TRAN / COMMIT / ROLLBACK control.

Engine id: `mssql` (SQLAlchemy dialect name; UI label is "SQL Server").
Driver: pymssql (FreeTDS) — chosen over pyodbc so the Linux Docker image needs no
Microsoft ODBC Driver install.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.connectors.base import ConnectionTestResult, Connector
from app.introspection import mssql as mssql_introspect
from app.introspection.normalized import Schema
from app.scripts.runner import ROW_CAP, STATEMENT_TIMEOUT_S, StatementResult, cap_rows

_JSON_PRIMITIVES = (type(None), bool, int, float, str)


def _jsonable(value: Any) -> Any:
    """Coerce a DB cell to JSON-carriable form (mirrors the Postgres/MySQL connectors)."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, (*_JSON_PRIMITIVES, list, dict)):
        return value
    return str(value)


def _build_dsn(creds: dict[str, Any]) -> str:
    user = quote_plus(str(creds["user"]))
    password = quote_plus(str(creds["password"]))
    host = creds["host"]
    port = int(creds.get("port", 1433))
    database = creds["database"]
    return f"mssql+pymssql://{user}:{password}@{host}:{port}/{database}"


def _connect_args(creds: dict[str, Any]) -> dict[str, Any]:
    """pymssql connect args. sslmode is accepted on the credential model for UI parity
    but FreeTDS encryption is typically configured outside the DSN; we only set timeouts.
    """
    _ = creds.get("sslmode")  # acknowledged; see engines.ts sslHint
    return {"login_timeout": 5, "timeout": 30}


class MSSQLConnector(Connector):
    engine = "mssql"

    def _engine(self) -> Engine:
        return create_engine(
            _build_dsn(self.credentials),
            pool_pre_ping=True,
            connect_args=_connect_args(self.credentials),
        )

    def test_connection(self) -> ConnectionTestResult:
        try:
            eng = self._engine()
            with eng.connect() as conn:
                version = conn.execute(text("SELECT @@VERSION")).scalar_one()
            # @@VERSION is multi-line; keep the first line for the UI badge.
            detail = str(version).splitlines()[0].strip() if version else "SQL Server"
            return ConnectionTestResult(ok=True, detail=detail)
        except SQLAlchemyError as e:
            return ConnectionTestResult(ok=False, detail=str(e.__cause__ or e))
        except Exception as e:
            return ConnectionTestResult(ok=False, detail=str(e))

    def introspect(self, *, connection_name: str | None = None, on_progress: Any = None) -> Schema:
        # Progress reporting not wired yet; params accepted for interface parity.
        return mssql_introspect.introspect(self._engine())

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
            dbapi = raw.driver_connection  # pymssql.Connection
            cur = dbapi.cursor()
            # Cap statement wait (ms). LOCK_TIMEOUT is the closest portable knob.
            cur.execute(f"SET LOCK_TIMEOUT {int(timeout_s) * 1000}")
            cur.execute("BEGIN TRANSACTION")
            if read_only:
                # SQL Server has no Postgres-style SET TRANSACTION READ ONLY that blocks
                # writes for all editions; we still roll back at the end in read_only mode.
                pass
            for index, stmt in enumerate(statements):
                started = time.perf_counter()
                try:
                    cur.execute(stmt)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    if cur.description:
                        fetched = cur.fetchmany(row_cap + 1)
                        capped, truncated = cap_rows(list(fetched), row_cap)
                        rows = [[_jsonable(v) for v in row] for row in capped]
                        results.append(
                            StatementResult(
                                index=index,
                                sql=stmt,
                                kind="rows",
                                columns=[d[0] for d in cur.description],
                                rows=rows,
                                row_count=len(rows),
                                truncated=truncated,
                                duration_ms=duration_ms,
                                error=None,
                            )
                        )
                    else:
                        affected = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                        results.append(
                            StatementResult(
                                index=index,
                                sql=stmt,
                                kind="command",
                                columns=[],
                                rows=[],
                                row_count=affected,
                                truncated=False,
                                duration_ms=duration_ms,
                                error=None,
                            )
                        )
                except Exception as e:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    msg = e.args[1] if getattr(e, "args", None) and len(e.args) > 1 else str(e)
                    results.append(
                        StatementResult(
                            index=index,
                            sql=stmt,
                            kind="error",
                            columns=[],
                            rows=[],
                            row_count=0,
                            truncated=False,
                            duration_ms=duration_ms,
                            error=str(msg),
                        )
                    )
                    errored = True
                    break
            if read_only or errored:
                dbapi.rollback()
            else:
                dbapi.commit()
        finally:
            raw.close()
        return results
