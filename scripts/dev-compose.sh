#!/usr/bin/env bash
# Run docker compose for local DataMETL with repo-root .env loaded for interpolation.
#
# Why this exists: `docker compose --env-file .env` alone is not enough. Variables
# already present in the process environment — including empty ones like
# AUTH_PASSWORD= — take precedence over the env-file. That left AUTH_ENABLED stuck
# false after a prior shell export, even when .env said true. Sourcing .env in this
# wrapper makes Makefile targets deterministic.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
COMPOSE_FILE="${ROOT}/infra/docker-compose.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ${ENV_FILE}." >&2
  echo "Copy .env.example to .env, set ENCRYPTION_KEY (make key), then retry." >&2
  exit 1
fi

if grep -qE '^ENCRYPTION_KEY=(CHANGE_ME_GENERATE_A_FERNET_KEY)?[[:space:]]*$' "$ENV_FILE"; then
  echo "ENCRYPTION_KEY in .env is missing or still a placeholder." >&2
  echo "Generate one with: make key" >&2
  echo "Then paste it into .env as ENCRYPTION_KEY=..." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
