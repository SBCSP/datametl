# Schema-per-tenant foundation (TENANT-SCHEMA)

**Product defaults (locked)**

- Team-on-install (not cloud SaaS)
- Schema-per-tenant: `public` control plane + one Postgres schema per tenant
- Schema naming: **`tenant_<uuid>`** → implemented as `tenant_` + `uuid.hex` (32 lowercase hex chars, no dashes), e.g. `tenant_00000000000040008000000000000001`
- Personal GitHub OAuth v1 (interfaces stubbed here; full OAuth = next milestone)
- Pro licenses are **tenant-scoped** (`tenant_licenses` stub)
- **No cross-tenant Mel**

**Milestone order (locked)**

1. **TENANT-SCHEMA** (this PR) — control models, provision, search_path, cutover, dual migration docs
2. **GITHUB-OAUTH** — personal GitHub OAuth (Knox for secrets)
3. **TENANT-ENFORCE** — bind every request/job to a tenant schema; reject cross-tenant Mel
4. **Staging smoke** — provision + cutover + OAuth login on Railway staging

PRs only — do not merge experiments straight to `main` without review.

---

## Dual migration strategy

### Public / control

- Alembic in `backend/alembic/` remains the install-wide migrator.
- Revision `0019_public_control_plane` creates `public.tenants`, `public.users`,
  `public.oauth_identities`, `public.tenant_memberships`, `public.tenant_licenses`
  with explicit `schema="public"`.
- Run as today: `make migrate` → `alembic upgrade head`.

### Tenant template

- Revisions `0001`–`0018` describe the historical single-tenant app schema
  (connections, Mel, mappings, pipelines, …). That shape is the **tenant template baseline**.
- Constant: `app.tenancy.migrate.TENANT_TEMPLATE_REVISION = "0018_chat_session_tool_cards"`.
- `upgrade_tenant_schema(schema_name)` / `create_tenant_schema(...)`:
  1. `CREATE SCHEMA IF NOT EXISTS tenant_<uuidhex>`
  2. `create_all(checkfirst=True)` for ORM tables that are **not** control-plane
  3. Stamp `{schema}.alembic_version` to `TENANT_TEMPLATE_REVISION`
- Control revisions must **not** be replayed inside a tenant schema.
- Future tenant-only DDL: extend the runner or add a dedicated tenant alembic branch
  (follow-up — intentionally not a giant rewrite of history in this PR).

Optional experimental: `alembic -x tenant_schema=tenant_<uuidhex> upgrade …`
sets `search_path` + `version_table_schema`. Prefer the Python provisioner for installs.

---

## Provision

```python
from app.tenancy import create_tenant_schema, provision_tenant, set_search_path

tenant = create_tenant_schema(db, kind="personal", name="Ada", owner_user_id=user.id)
# or
tenant, user = provision_tenant(db, kind="org", name="Acme", owner_email="a@acme.test")

set_search_path(db.connection(), tenant.schema_name)  # request/job binding
```

Kinds: `personal` | `org`.

---

## Session binding

`set_search_path(connection, schema_name)` → `SET search_path TO tenant_…, public`
so unqualified ORM tables hit the tenant schema while control tables in `public` stay visible.

Full request middleware enforcement is **TENANT-ENFORCE** (`TenantBindingMiddleware` is a no-op stub).

---

## Cutover (existing single-tenant data)

After `alembic upgrade head` (includes 0019):

```bash
# Dry-run (prints ALTER TABLE … SET SCHEMA …)
docker compose -f infra/docker-compose.yml run --rm backend \
  python -m app.scripts.cutover_tenant_schema

# Apply (quiesce writers first)
docker compose -f infra/docker-compose.yml run --rm backend \
  python -m app.scripts.cutover_tenant_schema --apply
```

Default cutover tenant id: `00000000-0000-4000-8000-000000000001`  
→ schema `tenant_00000000000040008000000000000001`.

Uses Postgres `ALTER TABLE … SET SCHEMA` (moves tables; data stays). Idempotent skip if a table is already absent from `public`.

---

## AUTH_LEGACY_BASIC

Env `AUTH_LEGACY_BASIC` (default `true`): keep the existing username/password login for one release while GitHub OAuth lands. Deprecate after GITHUB-OAUTH + TENANT-ENFORCE.

---

## Out of scope (follow-ups)

- Full GitHub OAuth UI/callback (see `app.tenancy.oauth` stubs)
- Rewriting every API route to bind tenant
- Moving all alembic history into a separate tenant track in one rewrite
