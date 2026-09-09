from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Dual migration strategy (see docs/TENANT_SCHEMA.md):
# - Default ``alembic upgrade head`` applies the public/control line (incl. 0019).
# - Per-tenant schemas are upgraded via ``app.tenancy.migrate.upgrade_tenant_schema``,
#   which stamps TENANT_TEMPLATE_REVISION (0018) — do not replay control DDL there.
# - Optional: ``alembic -x tenant_schema=tenant_<uuidhex> …`` sets search_path for
#   experimental tenant-scoped runs (version table stays in that schema).


def _tenant_schema_xarg() -> str | None:
    x = context.get_x_argument(as_dictionary=True)
    raw = (x.get("tenant_schema") or "").strip()
    return raw or None


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    tenant_schema = _tenant_schema_xarg()
    with connectable.connect() as connection:
        configure_kwargs: dict = {
            "connection": connection,
            "target_metadata": target_metadata,
            "include_schemas": True,
        }
        if tenant_schema:
            # Experimental path — prefer app.tenancy.migrate for provision/upgrade.
            from app.tenancy.names import assert_safe_schema_name

            name = assert_safe_schema_name(tenant_schema)
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))
            connection.execute(text(f"SET search_path TO {name}, public"))
            configure_kwargs["version_table_schema"] = name
        context.configure(**configure_kwargs)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
