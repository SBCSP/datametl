# DataMETL

A local-first data migration tool. The driving use case is migrating a **Supabase** database to vanilla **Postgres** (e.g. AWS RDS), with the architecture set up to extend to other engines later.

It runs on your laptop, never sends your database credentials anywhere, and lets you:

1. **Connect** to source + destination databases (Postgres today; pluggable for more).
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
- Downloads the latest release's `docker-compose.yml` + `.env.example`
- Generates a fresh Fernet encryption key into `.env`
- Pulls the multi-arch images from `ghcr.io/sbcsp/datametl-{backend,frontend}`
- Brings the stack up

Open <http://localhost:3000>. To stop: `cd datametl && docker compose down`. To update: `docker compose pull && docker compose up -d`.

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
cp .env.example .env
make key                      # generate a Fernet key, paste into ENCRYPTION_KEY in .env

make up-samples               # app + sample Supabase-flavored source + vanilla destination
make migrate                  # run alembic
```

Then open:

- Frontend: <http://localhost:3000>
- Backend OpenAPI: <http://localhost:8000/docs>

Sample DB credentials are in `.env.example` (`SAMPLE_SOURCE_PASSWORD`, `SAMPLE_DEST_PASSWORD`). Connect to them from the UI as your "source" and "destination" connections.

## Common commands

Run `make help` for the full list. Highlights:

| Task | Command |
|---|---|
| Generate a Fernet key | `make key` |
| Start dev stack (always rebuilds) | `make up` |
| With sample DBs | `make up-samples` |
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

## Architecture

See [CLAUDE.md](CLAUDE.md) for the architectural overview that future Claude Code sessions use.
