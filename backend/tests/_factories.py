"""Tiny in-memory builders for normalized Schema objects, so tests don't need a live DB."""
from __future__ import annotations

from app.introspection.normalized import Column, ForeignKeyRef, RlsPolicy, Schema, Table, View


def col(name: str, native: str, normalized: str, **kw) -> Column:
    return Column(name=name, native_type=native, normalized_type=normalized, nullable=kw.get("nullable", True),
                  default=kw.get("default"), is_primary_key=kw.get("pk", False),
                  foreign_key=kw.get("fk"))


def tbl(schema: str, name: str, columns: list[Column], **kw) -> Table:
    return Table(schema=schema, name=name, columns=columns,
                 indexes=kw.get("indexes", []),
                 row_count_estimate=kw.get("rows"),
                 rls_enabled=kw.get("rls", False))


def schema(tables: list[Table], **kw) -> Schema:
    return Schema(
        engine="postgres",
        server_version=kw.get("version", "16.0"),
        tables=tables,
        views=kw.get("views", []),
        extensions=kw.get("extensions", []),
        rls_policies=kw.get("policies", []),
    )


def fk(schema: str, table: str, column: str) -> ForeignKeyRef:
    return ForeignKeyRef(schema=schema, table=table, column=column)


def policy(schema: str, table: str, name: str, *, using: str | None = None,
           with_check: str | None = None, command: str = "SELECT") -> RlsPolicy:
    return RlsPolicy(schema=schema, table=table, name=name, command=command,
                     using_expr=using, with_check_expr=with_check)


def view(schema: str, name: str, definition: str) -> View:
    return View(schema=schema, name=name, definition=definition)
