# Schema-per-tenant foundation (TENANT-SCHEMA)

**Product defaults (locked)**

- Team-on-install (not cloud SaaS)
- Schema-per-tenant: `public` control plane + one Postgres schema per tenant
- Schema naming: **`tenant_<uuid>`** → implemented as `tenant_` + `uuid.hex` (32 lowercase hex chars, no dashes), e.g. `tenant_00000000000040008000000000000001`
- Personal GitHub OAuth v1 — see [GITHUB_OAUTH.md](./GITHUB_OAUTH.md)
- Pro licenses are **tenant-scoped** (`tenant_licenses` stub)
- **No cross-tenant Mel**

**Milestone order (locked)**

1. **TENANT-SCHEMA** (this PR) — control models, provision, search_path, cutover, dual migration docs
2. **GITHUB-OAUTH** — personal GitHub OAuth ([GITHUB_OAUTH.md](./GITHUB_OAUTH.md); Knox for secrets)
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

---

## TENANT-ENFORCE

Env `TENANT_ENFORCE_ENABLED` (default **`true`**): bind every authenticated request and
background job to a tenant schema. Staging keeps working via the cutover tenant +
`AUTH_LEGACY_BASIC` fallback.

### Request path

1. `TenantBindingMiddleware` (inside Auth, outside routes) resolves the bearer subject,
   loads `TenantMembership` rows, and picks the active tenant:
   - Header `X-Tenant-Id` if the user is a member of that tenant
   - Else the sole membership, or the earliest membership when several exist
   - Else, when auth is off or `AUTH_LEGACY_BASIC`, the cutover tenant
     `00000000-0000-4000-8000-000000000001` →
     `tenant_00000000000040008000000000000001` (if the control row exists)
2. Sets `request.state.tenant_context = TenantContext(...)` and a ContextVar used by
   `get_db()` / `enqueue()`.
3. `get_db()` calls `set_search_path` when context is present.
4. Skips binding for `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`,
   `/api/auth/login|status|github/*`, and the Stripe webhook.

### Jobs

`enqueue()` appends `tenant_id` from the request ContextVar. Worker tasks accept an
optional trailing `tenant_id` and open sessions via `open_tenant_session` (search_path
bound). Legacy jobs with no `tenant_id` default to the cutover tenant (warning log).

### Mel — no cross-tenant access

Chat / MCP Mel routes depend on `require_tenant_context`. When enforce is on and no
tenant is bound, they return **403** (`Tenant context required; no cross-tenant Mel.`).
Membership checks reject `X-Tenant-Id` for tenants the user does not belong to.

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

- Full GitHub OAuth login UI polish (backend start/callback shipped — see GITHUB_OAUTH.md)
- Rewriting every API route to bind tenant
- Moving all alembic history into a separate tenant track in one rewrite
