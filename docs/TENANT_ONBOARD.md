# Tenant onboarding (TENANT-ONBOARD-v1)

First-workspace gate after GitHub OAuth (or any session with a `public.users` row).

## Locked product rules

- Fields: **name**, **slug**, **kind** (`personal` | `organization` in API/FE; DB stores `org` for organization)
- `needs_onboarding` = authenticated user has **zero** `TenantMembership` rows
- Cutover tenant bind alone does **not** clear onboarding — the UI stays blocked until the user creates a workspace
- v1: **one workspace** per user (`POST` rejects if any membership exists)
- Out of scope: invites, switcher, billing, killing cutover globally, `use_case`

## API

| Method | Path | Auth | Notes |
|--------|------|------|--------|
| `GET` | `/api/tenants/me` | Bearer + mapped `User` | `{ needs_onboarding, tenants[] }` |
| `POST` | `/api/tenants` | Bearer + mapped `User` | Body `{ name, slug, kind }`; creates schema + owner membership |

Tenant binding middleware **skips** `/api/tenants*` so these routes work with no membership (still require AuthMiddleware).

## Slug

- Lowercase `[a-z0-9-]`, no leading/trailing hyphen
- Auto-suggested from name on the FE (`frontend/lib/slug.ts`); same rules in `app.tenancy.slug`

## Schema

Alembic `0020_tenant_slug` adds unique `public.tenants.slug` (backfills existing rows).

## FE

`AppShell` loads `api.tenantsMe` when auth is on and the user is signed in. If `needs_onboarding`, it renders `OnboardingModal` and does not mount app children.
