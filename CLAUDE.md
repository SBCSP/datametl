# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DataMETL is a local-first data migration tool. The driving real-world use case is migrating a **Supabase database to vanilla Postgres**. Phase 1 covers connection management, schema introspection, side-by-side comparison, and per-column datatype mapping. Phase 2 (current) executes the migration: pre-flight validation, streaming binary `COPY` between source and destination, post-load verification (row count + hash sampling + sequence parity), per-run history.

Stack: FastAPI + uv backend, Next.js + shadcn/ui frontend, Postgres metadata DB, arq + Redis job queue, all wrapped in docker-compose. Nothing runs on the host.

## Common commands

Everything goes through `make` (which shells out to `docker compose -f infra/docker-compose.yml`). Run `make help` for the full list. Key ones:

| Task | Command |
|---|---|
| Generate a Fernet key for `.env` | `make key` |
| Start app stack | `make up` |
| Start app + sample source/dest DBs | `make up-samples` |
| Stop everything | `make down` |
| Run alembic migrations | `make migrate` |
| Create a new alembic revision (autogenerate) | `make revision m="add foo"` |
| Open psql against the metadata DB | `make psql` |
| Run backend tests | `make test` |
| Lint backend | `make lint` |
| Typecheck backend | `make typecheck` |
| Tail all logs | `make logs` |
| Wipe volumes too | `make clean` |

To run a single backend test: `docker compose -f infra/docker-compose.yml run --rm backend pytest tests/test_diff.py::test_column_drift_kinds -xvs`

There is no `make test` for the frontend yet — run `npm run typecheck` or `npm run build` from inside the `frontend` container (or after `npm install` locally if you have Node 20).

## Architecture

### Backend layering

The five backend modules are deliberately decoupled. Phase 2 plugs in behind the same API without rewriting Phase 1.

```
connectors/        Pluggable per-engine drivers. Today: PostgresConnector. Each implements
                   test_connection() and introspect() — and later read_rows / write_rows.

introspection/     Engine-specific introspectors produce a single engine-agnostic shape:
                   Schema → Table → Column with `normalized_type` (string, int64, uuid, json…).
                   Everything downstream (comparison, mapping, frontend) operates on the
                   normalized shape and never knows what engine produced it.

recipes/           Engine-aware overlays that emit Warnings on top of an introspected Schema.
                   Today: supabase.py flags auth/storage/realtime schemas, RLS policies,
                   gen_random_uuid() defaults, FKs to auth.users, views/policies that call
                   auth.uid()/auth.role(). This is the layer that makes the tool worth
                   using vs. running pg_dump yourself.

comparison/        Pure schema diff: tables-only-in-{source,dest}, plus per-column drift
                   (type / nullable / default / pk / fk).

mapping/           Two pieces:
                     registry.py — default destination type per (source_engine, normalized_type,
                                   dest_engine). Same-engine preserves source native verbatim.
                     service.py  — auto-seeds Mapping rows when a comparison is created.
                                   User overrides are flagged lossy via registry._LOSSY_PAIRS.
```

Phase 2 modules (live):

```
strategies/        Pluggable per-strategy data movement. v1 ships LogicalCopyStrategy
                   (psycopg streaming binary COPY between source and destination, with
                   per-table TRUNCATE before load + post-load setval for sequence-backed PKs).

transforms/        column_plan.py — pure helper that turns mapping rows into the SELECT
                   expression list and INSERT column list the strategy uses. Handles
                   type cast (`col::dst_type`), rename (`col AS new_col`), and skip flag.

verification/      Run after the data move. row_count.py, hash_sample.py, sequence_parity.py.
                   runner.py picks which checks run based on the per-table `verification`
                   level. Results stored as JSONB on migration_run_tables.verification.

migrations/        ddl.py (CREATE TABLE preview text — never executes), pre_flight.py
                   (read-only validation: source readable, dest tables exist, mappings
                   cover columns, conflict-mode-vs-existing-data sanity), planner.py
                   (Comparison + table options → MigrationPlan), runner.py (executes
                   the plan, FK-deferred via session_replication_role=replica, topo-sorts
                   tables by FK dependency, calls strategy + verification per table,
                   updates MigrationRunTable rows live so the UI can poll).
```

Same async-job pattern as Phase 1: `POST /api/migrations/runs` returns `202 + {run_id, job_id}`. The worker runs `run_migration` (offloads sync COPY to a thread via `asyncio.to_thread` like introspection does). Frontend polls `/api/migrations/runs/{id}` every 1.5s until the run terminates.

### Why introspection/comparison/mapping run in arq, not the request handler

Introspecting a real Supabase project (hundreds of tables, RLS policies, view definitions) takes seconds-to-minutes. The API enqueues an arq job (`POST /api/connections/{id}/introspect` returns `202` + `job_id`); the frontend polls `GET /api/jobs/{job_id}`. Same shape for `POST /api/comparisons`. The worker process runs the same image as the backend with `command: arq app.jobs.worker.WorkerSettings`. See [backend/app/jobs/worker.py](backend/app/jobs/worker.py), [tasks.py](backend/app/jobs/tasks.py), [queue.py](backend/app/jobs/queue.py).

### Credential handling

User-supplied DB credentials are encrypted at rest with Fernet (symmetric, urlsafe base64 key from `ENCRYPTION_KEY`). Encryption happens in [backend/app/crypto.py](backend/app/crypto.py) before insert, decryption on use inside connector / job code. The **password and `sslrootcert` PEM are never returned** from the API. Non-secret connection metadata (host, port, database, user, sslmode, plus a `has_sslrootcert: bool`) is exposed via the `redacted_credentials` field on `ConnectionDetail` so the edit form can pre-fill — see [`_redact()`](backend/app/api/connections.py). When working in this codebase: do not log decrypted credentials, do not add them to error messages, do not extend `redacted_credentials` to include the password or PEM.

### Metadata DB

DataMETL has its own Postgres (the `app-postgres` compose service) for storing connections, schema snapshots, comparisons, and mappings. This is separate from any user-supplied source/destination DB. SQLAlchemy 2.0 ORM + Alembic. Models live under [backend/app/models/](backend/app/models/) and are all exported from `app.models` so `Base.metadata` is fully populated for autogeneration.

Snapshots store the full normalized schema as JSONB (with the warnings array alongside) — comparisons and mappings reference snapshots, not live introspections, so they're stable and reproducible.

### Frontend

App Router, TypeScript, TanStack Query for all server state, shadcn/ui (new-york style, slate base) for components — `components/ui/` are local copies, not a dependency. The API client is hand-written in [frontend/lib/api.ts](frontend/lib/api.ts) and types mirror the backend pydantic schemas in [frontend/lib/types.ts](frontend/lib/types.ts) — keep them in sync when changing backend schemas. Long-running operations use [frontend/lib/use-job.ts](frontend/lib/use-job.ts) which polls `/api/jobs/{id}` until `complete`.

### docker-compose layout

Two compose files:
- [infra/docker-compose.yml](infra/docker-compose.yml) — always-on: app-postgres, redis, backend, worker, frontend.
- [infra/docker-compose.samples.yml](infra/docker-compose.samples.yml) — opt-in (`profile: samples`): sample-source (Supabase-flavored, seeded from `infra/seed/supabase-source.sql`) and sample-dest (vanilla, seeded from `infra/seed/vanilla-dest.sql`). `make up-samples` brings up both.

Backend and worker share a single image; the worker just overrides `command:`. Both bind-mount the `backend/` directory for live reload, with an anonymous volume on `.venv` so the host's empty `.venv` doesn't shadow the container's.

## Code conventions worth knowing

- **Normalized type vocabulary** is intentionally small (see `NormalizedType` in [backend/app/introspection/normalized.py](backend/app/introspection/normalized.py)). Don't add a new normalized type unless you also extend the registry default mapping for every engine you support.
- **Recipes never mutate the Schema** — they only emit `Warning` objects that the frontend renders as banners. This keeps the introspected shape engine-pure.
- **Pydantic models with Python keywords as fields** (`schema`) use `schema_` with `Field(alias="schema")` and `populate_by_name=True`. When dumping, use `model_dump(by_alias=True)` so the JSON shape stays `schema`.
- **Tests are pure-logic by default** — `tests/_factories.py` builds Schema objects in memory. Live-DB testing happens via the sample compose profile, not pytest.

## End-to-end smoke test

```
cp .env.example .env && make key   # paste the printed key into ENCRYPTION_KEY
make up-samples
make migrate
# Open http://localhost:3000
#   1. Create two connections — see infra/docker-compose.samples.yml for sample creds
#      (host: sample-source / sample-dest, port: 5432 from inside the network, but if
#       connecting from the browser-served new-connection form the backend reaches the
#       sample DBs by their compose service name, so use sample-source / sample-dest as host)
#   2. Test each → green.
#   3. Introspect each. Source snapshot should warn about the auth schema, RLS, gen_random_uuid().
#   4. Create a comparison — diff shows public.profiles only-in-source, public.posts with
#      column drift on metadata, view_count, created_at type.
#   5. Open mappings — defaults populated; override one column's type and watch the lossy badge.
```

## What NOT to do here

- Don't add Supabase-specific logic to `connectors/postgres.py` or `introspection/postgres.py` — Supabase awareness lives in `recipes/supabase.py` only. The introspector treats Supabase as plain Postgres.
- Don't return credentials from API endpoints, even for "internal" routes. There are no internal routes — this binds to localhost but the boundary still matters.
- Don't introduce app-level auth in Phase 1. The user explicitly opted out.
- Don't bypass arq for "quick" operations. If it touches a user-supplied DB, it goes through the worker.
- **Phase 2 only ever writes to the destination, never the source.** The strategy opens an explicit `SET TRANSACTION READ ONLY` on the source connection. If you add a new strategy or modify the existing one, preserve that invariant.
- **Phase 2 does not auto-`CREATE TABLE`.** Tables only on source are surfaced as DDL preview the user copies/runs themselves. Don't change this without an explicit user-facing safeguard.
