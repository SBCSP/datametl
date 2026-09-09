"""Canonical tenant schema naming: ``tenant_<uuidhex>``."""
from __future__ import annotations

import re
import uuid

SCHEMA_NAME_PREFIX = "tenant_"
# tenant_ + 32 lowercase hex chars (uuid.UUID.hex)
_SCHEMA_RE = re.compile(rf"^{SCHEMA_NAME_PREFIX}[0-9a-f]{{32}}$")


def tenant_schema_name(tenant_id: uuid.UUID) -> str:
    """Return the Postgres schema name for a tenant id.

    Locked product form: ``tenant_<uuid>`` implemented as ``tenant_`` + ``uuid.hex``
    (no dashes) so the identifier is unquoted-safe in Postgres.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a uuid.UUID")
    return f"{SCHEMA_NAME_PREFIX}{tenant_id.hex}"


def is_valid_tenant_schema_name(schema_name: str) -> bool:
    return bool(_SCHEMA_RE.fullmatch(schema_name or ""))


def tenant_id_from_schema_name(schema_name: str) -> uuid.UUID:
    if not is_valid_tenant_schema_name(schema_name):
        raise ValueError(f"invalid tenant schema name: {schema_name!r}")
    return uuid.UUID(hex=schema_name[len(SCHEMA_NAME_PREFIX) :])


def assert_safe_schema_name(schema_name: str) -> str:
    """Validate before interpolating into DDL. Raises ValueError if unsafe."""
    if not is_valid_tenant_schema_name(schema_name):
        raise ValueError(f"refusing unsafe schema name: {schema_name!r}")
    return schema_name
