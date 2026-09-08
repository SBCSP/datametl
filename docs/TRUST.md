# DataMETL Trust & Security

Honest notes on where your data goes. This page mirrors what the product does today — no SSO/RBAC/Team claims beyond what ships.

## Local-first credentials

- Database connection secrets (password, optional SSL CA PEM) stay on **your machine** and the **Docker network you run**. They are **never** sent to SandboxCSP or any DataMETL vendor cloud.
- Credentials are encrypted **at rest** with **Fernet** (`ENCRYPTION_KEY` in `.env`) before storage in the app metadata database. See `backend/app/crypto.py`.
- The API never returns passwords or CA PEMs; edit forms only get redacted connection metadata (`has_sslrootcert`, host, port, user, etc.).

## Mel and Anthropic

Mel (in-app chat) uses **your** Anthropic API key (stored encrypted at rest, same Fernet vault).

When Mel calls live DB tools against an activated MCP connection, Anthropic receives:

- Your chat **prompts** and Mel’s system instructions
- **Tool results** only — schema listings, `describe_table` column metadata, and **query row samples capped at `TOOL_ROW_CAP` (200 rows)** (`backend/app/mcp/tools.py`)

**Not** sent to the LLM:

- Database passwords / connection secrets
- Your Fernet `ENCRYPTION_KEY`
- Stripe or license signing keys

Tool execution decrypts credentials **locally** inside the backend, runs read-only SQL on your network, then returns capped JSON results to the model.

Without an active MCP connection, Mel is advisory only (no live DB access).

## MCP tools are read-only

Live Mel tools (`list_tables`, `describe_table`, `run_sql`) always use `run_statements(..., read_only=True)` — writes and DDL are rejected. Results inherit the 200-row cap and a 30s tool timeout.

### Approve-to-run

Settings → Mel **tool approval** modes:

| Mode | Behavior |
|------|----------|
| `run_sql_only` (Pro default) | `run_sql` waits for Approve/Deny in chat; list/describe may auto-run |
| `always` | Every Mel DB tool needs Approve |
| `auto` | No approval prompts (still read-only) |

**Community** (no license key): Mel is allowed, but approval is **forced to `always`**.

### Audit

Every Mel tool proposal is recorded (`mel_tool_invocations`) with redacted args, decision, and outcome. Browse recent activity from **Runs** / Mel audit surfaces (`GET /api/chat/mel-audit`).

## Licensing (offline verify)

- Self-hosted **Pro** uses **offline-verifiable** Ed25519 signed keys (`dmtl1.…`). Verification needs no network call to SandboxCSP.
- **Stripe secrets** (`STRIPE_SECRET_KEY`, webhook secret, `LICENSE_SIGNING_KEY`) belong only on a **vendor issuer** machine (Phase 2 webhook). Normal Community / Pro installs paste a key in Settings — they do **not** need Stripe.
- **Team** is an entitlement stub only; multi-user SSO/RBAC is **not** shipped in-app (Helm can put oauth2-proxy/Keycloak at the edge separately).

### External FastMCP (Pro)

Cursor / Claude Desktop can connect to DataMETL’s FastMCP endpoint at `/mcp/external` (or stdio via `python -m app.mcp`). **Pro only** — Community receives HTTP 402. Tools stay read-only, use the same Mel approval mode, Redis Approve/Deny waiters, and `mel_tool_invocations` audit rows (`model=fastmcp`). Pending proposals are resolved with `POST /api/chat/tool-decision`.

## Community vs Pro

| | Community | Pro |
|---|-----------|-----|
| Postgres migrate / introspect / compare / verify | Yes | Yes |
| Mel chat | Yes | Yes |
| Mel tool approval modes | Forced `always` | `run_sql_only` / `always` / `auto` |
| External FastMCP (`/mcp/external`) | Not available (HTTP 402) | Same approve-to-run + audit as Mel |
| MySQL + SQL Server connectors | No | Yes |
| License key | None | Signed `dmtl1.…` (Ed25519) |
| Stripe on your install | Not required | Not required |

## What we do **not** claim (yet)

- Built-in multi-user accounts, viewer/operator RBAC, or Team SSO as a product feature
- That query **row contents** never leave your network when Mel tools run — samples **do** go to Anthropic as tool results (capped). Credentials do not.
- A live (non-test) Stripe Payment Link unless you configure one; the default sandbox link is test-mode.

For a website-ready summary, see [LAUNCH.md](./LAUNCH.md).
