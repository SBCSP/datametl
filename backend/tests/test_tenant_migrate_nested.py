"""upgrade_tenant_schema must not nest begin() on a Session-bound connection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy.engine import Connection

from app.tenancy.migrate import upgrade_tenant_schema


def test_upgrade_tenant_schema_no_nested_begin_on_connection() -> None:
    conn = MagicMock(spec=Connection)
    conn.begin.side_effect = AssertionError("must not call begin() on session-bound connection")

    with (
        patch("app.tenancy.migrate.clone_tenant_metadata") as clone,
        patch("app.tenancy.migrate.stamp_tenant_revision") as stamp,
        patch("app.tenancy.migrate.assert_safe_schema_name", side_effect=lambda s: s),
    ):
        meta = MagicMock()
        clone.return_value = meta
        rev = upgrade_tenant_schema(conn, "tenant_abcdef0123456789abcdef0123456789")
        assert rev == "0018_chat_session_tool_cards"
        conn.begin.assert_not_called()
        meta.create_all.assert_called_once()
        stamp.assert_called_once()
