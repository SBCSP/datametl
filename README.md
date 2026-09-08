# DataMETL

A local-first database migration tool for **PostgreSQL** (including managed Postgres such as AWS RDS). Connect a source and destination, compare their schemas, map datatypes, move the data, and verify parity. The connector and introspection layers are **pluggable** — Postgres is supported today, and additional engines (MySQL is next) slot in without touching the rest of the app.

It runs on your laptop, never sends your database credentials anywhere, and lets you:

1. **Connect** to source + destination databases (Postgres today; more engines being added).
2. **Introspect** each schema (tables, columns, datatypes, defaults, FKs, indexes, RLS policies, extensions).
3. **Compare** source vs. destination side-by-side at the schema level — with per-schema scoping.
4. **Map** datatypes from source to destination, with sensible defaults and per-column overrides.
5. **Migrate** the data via streaming binary `COPY` with per-table conflict modes.
6. **Verify** parity with row counts + hash sampling + sequence checks (also runs as a standalone tool).

![DataMETL](./images/DataMETL.jpg)

## Quick install (no git clone needed)

If you just want to run DataMETL — not develop it — this is the path:

```bash
curl -fsSL https://github.com/sbcsp/datametl/releases/latest/download/install.sh | bash
```

The installer:
- Verifies Docker is installed
- Creates a `datametl/` directory in your CWD
- Downloads the latest release's `docker-compose.yml` + `env.example`
- Generates a fresh Fernet encryption key into `.env`
- Drops a small `Makefile` so day-to-day commands match the dev workflow
- Pulls the multi-arch images from `ghcr.io/sbcsp/datametl-{backend,frontend}`
- Brings the stack up

Open <http://localhost:3000>. From the install directory:

```bash
make down       # stop the stack (data persists in named volumes)
make update     # pull latest images + restart
make logs       # tail logs
make help       # full target list
```

A specific version:
```bash
DATAMETL_VERSION=v0.2.0 INSTALL_DIR=~/datametl bash <(curl -fsSL https://github.com/sbcsp/datametl/releases/v0.2.0/download/install.sh)
```

The deploy compose only exposes one host port (`FRONTEND_PORT`, default 3000). The frontend container proxies API calls to the backend container internally — no CORS, no port-juggling.

## Stack

- **Backend:** Python 3.12 + FastAPI, managed with [uv](https://docs.astral.sh/uv)
- **Frontend:** Next.js (App Router) + TypeScript + [shadcn/ui](https://ui.shadcn.com) + Tailwind + TanStack Query
- **App metadata DB:** Postgres 16
- **Job queue:** [arq](https://arq-docs.helpmanual.io) on Redis
- **Everything runs in docker-compose** — no host-level Python or Node required.

## Develop on it (clone + run from source)

```bash
git clone https://github.com/sbcsp/datametl.git && cd datametl
make ensure-env               # creates .env from example + fresh ENCRYPTION_KEY
# optional: set AUTH_ENABLED=true (and username/password) in .env

make up-samples               # builds, starts, and runs migrations
```

`make up` / `make up-samples` always load `.env` via `scripts/dev-compose.sh` so values like `AUTH_*` win even if your shell has stale exports. Prefer Makefile targets over raw `docker compose`.

Then open:

- Frontend: <http://localhost:3005>
- Backend OpenAPI: <http://localhost:8001/docs>
- API health: <http://localhost:8001/health>

Sample DB credentials are in `.env.example` (`SAMPLE_SOURCE_PASSWORD`, `SAMPLE_DEST_PASSWORD`). Connect to them from the UI as your "source" and "destination" connections.

Optional MySQL / SQL Server test engines (not started by `make up`):

```bash
make up-mysql      # MySQL 8 on host :3307 — UI host engine-mysql:3306
make up-mssql      # SQL Server 2022 on host :14333 — UI host engine-mssql:1433
make up-engines    # both
make db-urls       # print connection hints (compose hostnames for the UI)
```

Passwords: `ENGINE_MYSQL_PASSWORD`, `ENGINE_MSSQL_PASSWORD` in `.env.example`. Engine id for SQL Server in the app is `mssql`.

## Common commands

Run `make help` for the full list. Highlights:

| Task | Command |
|---|---|
| Generate a Fernet key | `make key` |
| Create/validate `.env` | `make ensure-env` |
| Start dev stack (build + migrate) | `make up` |
| With sample DBs | `make up-samples` |
| MySQL / SQL Server test engines | `make up-mysql` / `make up-mssql` / `make up-engines` |
| Print DB connection hints | `make db-urls` |
| Apply migrations | `make migrate` |
| Tail logs | `make logs` |
| Run backend tests | `make test` |
| Cut a release (publish to GHCR) | `make release v=v0.2.1` |

## Releasing (maintainer guide)

DataMETL ships as multi-arch container images on GHCR plus a downloadable `docker-compose.yml` + `install.sh` attached to each GitHub release.

```bash
make release v=v0.2.1
```

That tags `v0.2.1`, pushes the tag, and the `.github/workflows/release.yml` workflow:
1. Builds `linux/amd64` + `linux/arm64` images for backend + frontend
2. Publishes them to `ghcr.io/sbcsp/datametl-{backend,frontend}:{v0.2.1,latest}`
3. Stages the deploy compose with version pinned and attaches it to the GitHub release alongside `install.sh`

End users then run the one-liner above and pull the freshly-published images.

## Deploy security notes

- **Sit behind SSO** (oauth2-proxy / Keycloak / similar) **or** set `AUTH_ENABLED=true` with a strong `AUTH_PASSWORD` before exposing the UI.
- `install.sh` / `make deploy-up` generate a Fernet `ENCRYPTION_KEY` and a strong `APP_DB_PASSWORD` — never commit `.env` / `.env.deploy`.
- Empty or `CHANGE_ME` encryption keys are refused at startup.
- Deploy compose disables OpenAPI `/docs` by default (`DOCS_ENABLED=false`). Set `DOCS_ENABLED=true` only on trusted networks.
- Protect `/metrics` with `METRICS_TOKEN` when the scrape endpoint is reachable beyond a trusted network.

## Architecture

See [CLAUDE.md](CLAUDE.md) for the architectural overview that future Claude Code sessions use.
