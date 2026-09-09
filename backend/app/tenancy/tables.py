"""Which SQLAlchemy tables belong in a tenant schema vs public control."""
from __future__ import annotations

from sqlalchemy import MetaData, Table

from app.models import Base

# Public control-plane tables (see app.models.tenant_control).
CONTROL_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "tenants",
        "users",
        "oauth_identities",
        "tenant_memberships",
        "tenant_licenses",
    }
)

VERSION_TABLE_NAME = "alembic_version"


def iter_tenant_tables() -> list[Table]:
    """ORM tables that belong in each tenant schema.

    Control models declare ``schema="public"``. Legacy app models have ``schema=None``
    and are the tenant template baseline (historically created in public; cutover moves
    them into ``tenant_<uuidhex>``).
    """
    out: list[Table] = []
    for table in Base.metadata.sorted_tables:
        if table.name in CONTROL_TABLE_NAMES:
            continue
        if table.schema == "public":
            continue
        out.append(table)
    return out


def tenant_table_names() -> frozenset[str]:
    return frozenset(t.name for t in iter_tenant_tables())


def clone_tenant_metadata(schema_name: str) -> MetaData:
    """MetaData with copies of tenant ORM tables targeted at ``schema_name``."""
    meta = MetaData()
    for table in iter_tenant_tables():
        table.to_metadata(meta, schema=schema_name)
    return meta
