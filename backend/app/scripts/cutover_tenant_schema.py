"""Management entrypoint: dry-run / apply SET SCHEMA cutover into the default tenant.

Usage (inside backend container / venv)::

    python -m app.scripts.cutover_tenant_schema           # dry-run SQL
    python -m app.scripts.cutover_tenant_schema --apply   # execute (quiesce writers first)

Creates the default tenant control row if missing. See docs/TENANT_SCHEMA.md.
"""
from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.tenancy.cutover import (
    DEFAULT_CUTOVER_TENANT_ID,
    cutover_public_to_tenant,
    ensure_default_tenant_row,
)
from app.tenancy.names import tenant_schema_name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute SET SCHEMA (default is dry-run only)",
    )
    parser.add_argument(
        "--name",
        default="Default",
        help="Display name for the default cutover tenant row",
    )
    args = parser.parse_args(argv)

    schema_name = tenant_schema_name(DEFAULT_CUTOVER_TENANT_ID)
    db = SessionLocal()
    try:
        tenant = ensure_default_tenant_row(db, name=args.name)
        print(f"tenant_id={tenant.id}")
        print(f"schema_name={tenant.schema_name}")
        stmts = cutover_public_to_tenant(db, schema_name, dry_run=not args.apply)
        print("-- SET SCHEMA plan --")
        for s in stmts:
            print(s + ";")
        if not args.apply:
            print("\nDry-run only. Re-run with --apply after quiescing writers.", file=sys.stderr)
        else:
            print("\nCutover applied.", file=sys.stderr)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
