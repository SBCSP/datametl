# Personal GitHub OAuth v1 (GITHUB-OAUTH)

Milestone **2** after TENANT-SCHEMA. Wires `app.tenancy.oauth.GitHubOAuthProvider` and
`/api/auth/github/*` so an install can log in with a GitHub identity linked to
`public.users` + `public.oauth_identities`.

## Env names (no live secrets in repo)

| Variable | Purpose |
| --- | --- |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App client id |
| `GITHUB_OAUTH_CLIENT_SECRET` | Client secret (Knox / deploy secret store — never commit) |
| `GITHUB_OAUTH_REDIRECT_URI` | Callback URL registered on the OAuth App (e.g. `https://host/api/auth/github/callback`) |

All three must be non-empty or the feature stays **disabled** (start/callback return HTTP 503 with a clear message).

Also required for login flows: `AUTH_ENABLED=true`. Keep `AUTH_LEGACY_BASIC=true` for one release if you still need username/password alongside OAuth.

## Routes

- `GET /api/auth/github/start` — 302 to GitHub authorize (or `?json=1` → `{authorize_url, state}`)
- `GET /api/auth/github/callback?code=&state=` — exchanges code via httpx, links `OAuthIdentity`, returns the same bearer `LoginResponse` as `/api/auth/login`
- `GET /api/auth/status` — includes `github_oauth_enabled` / `legacy_basic_enabled`

Access tokens from GitHub are **not** persisted on `OAuthIdentity.profile` (non-secret profile stub only).

## Local setup sketch

1. Create a GitHub OAuth App; set callback to your backend callback URL.
2. Put id / secret / redirect URI in `.env` (see `.env.example`).
3. `AUTH_ENABLED=true`, restart backend, open `/api/auth/github/start`.

## Out of scope

- Full login UI polish / frontend redirect landing page
- TENANT-ENFORCE (request → tenant schema binding)
- Storing GitHub tokens for API calls as the user
