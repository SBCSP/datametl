"""Schema-per-tenant foundation (team-on-install).

Milestone order (locked):
  1. TENANT-SCHEMA (this package) → 2. GITHUB-OAUTH personal → 3. TENANT-ENFORCE → 4. staging smoke

Schema names are always ``tenant_<uuidhex>`` (UUID.hex, 32 lowercase hex chars).
"""
from __future__ import annotations

from app.tenancy.migrate import TENANT_TEMPLATE_REVISION, upgrade_tenant_schema
from app.tenancy.names import (
    SCHEMA_NAME_PREFIX,
    is_valid_tenant_schema_name,
    tenant_id_from_schema_name,
    tenant_schema_name,
)
from app.tenancy.provision import create_tenant_schema, provision_tenant
from app.tenancy.search_path import set_search_path

__all__ = [
    "SCHEMA_NAME_PREFIX",
    "TENANT_TEMPLATE_REVISION",
    "create_tenant_schema",
    "is_valid_tenant_schema_name",
    "provision_tenant",
    "set_search_path",
    "tenant_id_from_schema_name",
    "tenant_schema_name",
    "upgrade_tenant_schema",
]
