"""Unit tests for schema-per-tenant naming, search_path, control metadata, cutover plan."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.models import Base
from app.models.tenant_control import (
    OAuthIdentity,
    Tenant,
    TenantLicense,
    TenantMembership,
    User,
)
from app.tenancy.cutover import (
    DEFAULT_CUTOVER_TENANT_ID,
    plan_set_schema_statements,
)
from app.tenancy.migrate import TENANT_TEMPLATE_REVISION
from app.tenancy.names import (
    is_valid_tenant_schema_name,
    tenant_id_from_schema_name,
    tenant_schema_name,
)
from app.tenancy.search_path import set_search_path
from app.tenancy.tables import CONTROL_TABLE_NAMES, clone_tenant_metadata, tenant_table_names


def test_tenant_schema_name_is_tenant_uuidhex() -> None:
    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert tenant_schema_name(tid) == "tenant_12345678123456781234567812345678"
    assert is_valid_tenant_schema_name(tenant_schema_name(tid))
    assert tenant_id_from_schema_name(tenant_schema_name(tid)) == tid


def test_rejects_old_t_prefix_and_dashed_uuid() -> None:
    assert not is_valid_tenant_schema_name("t_12345678123456781234567812345678")
    assert not is_valid_tenant_schema_name("tenant_12345678-1234-5678-1234-567812345678")
    assert not is_valid_tenant_schema_name("public")
    with pytest.raises(ValueError):
        tenant_id_from_schema_name("tenant_nope")


def test_set_search_path_executes_safe_sql() -> None:
    tid = uuid.uuid4()
    schema = tenant_schema_name(tid)
    conn = MagicMock()
    set_search_path(conn, schema)
    assert conn.execute.called
    sql = str(conn.execute.call_args[0][0])
    assert f"SET search_path TO {schema}, public" in sql


def test_set_search_path_rejects_unsafe_name() -> None:
    conn = MagicMock()
    with pytest.raises(ValueError):
        set_search_path(conn, "tenant_../evil")
    conn.execute.assert_not_called()


def test_control_models_are_public_schema() -> None:
    for model in (Tenant, User, OAuthIdentity, TenantMembership, TenantLicense):
        assert model.__table__.schema == "public"
        assert model.__tablename__ in CONTROL_TABLE_NAMES


def test_tenant_tables_exclude_control() -> None:
    names = tenant_table_names()
    assert "connections" in names
    assert "chat_sessions" in names
    assert "mel_tool_invocations" in names
    assert names.isdisjoint(CONTROL_TABLE_NAMES)
    # Control tables must not appear in cloned tenant metadata.
    meta = clone_tenant_metadata(tenant_schema_name(uuid.uuid4()))
    assert CONTROL_TABLE_NAMES.isdisjoint({t.name for t in meta.tables.values()})
    # Base still has both.
    assert "tenants" in Base.metadata.tables or any(
        t.name == "tenants" for t in Base.metadata.tables.values()
    )


def test_cutover_plan_uses_set_schema_and_default_id() -> None:
    schema = tenant_schema_name(DEFAULT_CUTOVER_TENANT_ID)
    assert schema == "tenant_00000000000040008000000000000001"
    stmts = plan_set_schema_statements(schema)
    assert stmts
    assert all(s.startswith("ALTER TABLE public.") and f'SET SCHEMA "{schema}"' in s for s in stmts)
    assert any('"connections"' in s for s in stmts)
    assert not any('"tenants"' in s for s in stmts)


def test_tenant_template_revision_is_pre_control() -> None:
    assert TENANT_TEMPLATE_REVISION == "0018_chat_session_tool_cards"
