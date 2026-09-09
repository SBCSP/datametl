"""Bind worker/job DB sessions to a tenant schema via search_path."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.tenant_control import Tenant
from app.tenancy.context import reset_tenant_context, set_tenant_context
from app.tenancy.cutover import DEFAULT_CUTOVER_TENANT_ID
from app.tenancy.middleware import TenantContext
from app.tenancy.names import tenant_schema_name
from app.tenancy.search_path import set_search_path

log = logging.getLogger("datametl.tenancy.job_bind")


def resolve_job_schema(db: Session, tenant_id: str | None) -> tuple[uuid.UUID, str]:
    """Return (tenant_id, schema_name) for a job. Legacy jobs with no tenant_id → cutover."""
    if tenant_id:
        tid = uuid.UUID(str(tenant_id))
        tenant = db.get(Tenant, tid)
        if tenant is not None:
            return tenant.id, tenant.schema_name
        # Tenant id provided but row missing — still use canonical schema name.
        log.warning("job tenant_id=%s not in control plane; using canonical schema name", tid)
        return tid, tenant_schema_name(tid)

    if settings.tenant_enforce_enabled:
        log.warning(
            "job missing tenant_id; defaulting to cutover tenant %s",
            DEFAULT_CUTOVER_TENANT_ID,
        )
    tid = DEFAULT_CUTOVER_TENANT_ID
    tenant = db.get(Tenant, tid)
    schema = tenant.schema_name if tenant is not None else tenant_schema_name(tid)
    return tid, schema


@contextmanager
def open_tenant_session(tenant_id: str | None = None) -> Generator[Session, None, None]:
    """Open a SessionLocal bound to the job's tenant search_path (+ contextvar)."""
    db = SessionLocal()
    token = None
    try:
        if settings.tenant_enforce_enabled:
            tid, schema = resolve_job_schema(db, tenant_id)
            set_search_path(db.connection(), schema)
            token = set_tenant_context(
                TenantContext(tenant_id=tid, schema_name=schema, role=None)
            )
        yield db
    finally:
        if token is not None:
            reset_tenant_context(token)
        db.close()
