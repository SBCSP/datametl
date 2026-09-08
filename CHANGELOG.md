# Changelog

All notable changes to DataMETL are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) where tagged releases exist.

## [Unreleased]

### Added

- In-app **Trust** page at `/trust` (sidebar + Settings links) and `docs/TRUST.md` / `docs/LAUNCH.md` launch copy.
- Product pitch polish at the top of the README (Mel, migrate, local-first, install one-liner, Buy Pro).

## [2026-09-08] — Mel, engines, licensing

### Added

#### Mel productization

- Approve-to-run for Mel DB tools (`run_sql_only` / `always` / `auto`) with chat Approve/Deny cards.
- Mel tool **audit** trail (`mel_tool_invocations`, redacted args) and activity / Runs surfaces.
- Ambient **Ask Mel** deep-links from Connections, Schemas, Comparisons, and Migrations (optional MCP activate + prefilled prompt).
- Community tier forces Mel approval to `always`; Pro can choose modes.

#### Engines — MySQL / SQL Server

- **SQL Server (`mssql`)** connector + introspection, datatype mapping hooks.
- Optional compose sidecars: `make up-mysql` / `make up-mssql` / `make up-engines`.
- Connection **new** flow: engine-first picker with Pro-gated MySQL/MSSQL (Community remains Postgres-first).

#### Phase 1 — Offline Pro licensing

- Ed25519 offline-verifiable license keys (`dmtl1.…`).
- Settings → License activate / deactivate; keys stored encrypted at rest.
- Entitlements: Pro unlocks MySQL/MSSQL + Mel approval choice; Community Mel approval forced to `always`.
- Maintainer tooling: `make license-keypair`, `make license-issue`; optional `DATAMETL_LICENSE_DEV_BYPASS` for local docker.

#### Phase 2 — Stripe issuer (vendor only)

- Stripe webhook issuer mints Pro keys on Payment Link checkout (`checkout.session.completed` and related events).
- Stripe secrets only required on the issuer machine — self-hosted installs paste a key and never need them.
- Settings **Buy Pro** button when `NEXT_PUBLIC_DATAMETL_PRO_URL` is set.
- Sandbox Payment Link (test mode): `https://buy.stripe.com/test_6oU8wQ9cL1Bv3Av9cw7ok00` ($79/mo Pro price in Stripe sandbox).

### Notes

- Team tier remains an entitlement stub (no in-app multi-user SSO/RBAC yet).
- Helm oauth2-proxy / Keycloak edge SSO is unchanged and separate from license tiers.

## Earlier

See git history for prior work (MCP / Mel chat foundation, pipelines, taps, SQL scripts, Helm deploy, install.sh releases).
