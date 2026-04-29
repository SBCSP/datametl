#!/usr/bin/env bash
#
# DataMETL one-line installer. Pulls the latest release's docker-compose.yml + .env.example,
# generates a Fernet encryption key, and starts the stack.
#
#   curl -fsSL https://github.com/sbcsp/datametl/releases/latest/download/install.sh | bash
#
# Or with a specific version + custom install dir:
#
#   DATAMETL_VERSION=v0.2.0 INSTALL_DIR=~/datametl bash <(curl ...)

set -euo pipefail

REPO="sbcsp/datametl"
RELEASE="${DATAMETL_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-./datametl}"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
info()   { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn()   { printf '\033[33m!\033[0m %s\n' "$*" >&2; }
err()    { printf '\033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

# --- Pre-flight ---
command -v docker >/dev/null 2>&1 || err "Docker is required. Install Docker Desktop (macOS/Windows) or Docker Engine (Linux) first."
docker compose version >/dev/null 2>&1 || err "Docker Compose v2 plugin is required (\"docker compose\", not \"docker-compose\")."
command -v curl >/dev/null 2>&1 || err "curl is required."
command -v openssl >/dev/null 2>&1 || err "openssl is required (used to generate the Fernet encryption key)."

# --- Download ---
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ "$RELEASE" = "latest" ]; then
  BASE="https://github.com/${REPO}/releases/latest/download"
else
  BASE="https://github.com/${REPO}/releases/download/${RELEASE}"
fi

info "Downloading from ${BASE}"
curl -fsSL "${BASE}/docker-compose.yml" -o docker-compose.yml \
  || err "Could not fetch docker-compose.yml. Is the release tag valid?"
curl -fsSL "${BASE}/.env.example" -o .env.example \
  || err "Could not fetch .env.example."

# Older releases sed-pinned the image tags to a specific version. Newer releases ship
# with the ${DATAMETL_VERSION:-latest} template intact. Normalize either way so that
# DATAMETL_VERSION in the user's .env always controls which images get pulled.
SED_INPLACE=(-i)
if [ "$(uname)" = "Darwin" ]; then
  SED_INPLACE=(-i '')
fi
sed "${SED_INPLACE[@]}" -E \
  -e 's|(ghcr\.io/sbcsp/datametl-(backend|frontend)):[^[:space:]"$]+|\1:${DATAMETL_VERSION:-latest}|g' \
  docker-compose.yml || true

# --- Generate Fernet key ---
# A Fernet key is 32 random bytes encoded as urlsafe base64. openssl produces standard
# base64; tr '+/' '-_' converts it to urlsafe form. The padding stays valid.
generate_key() {
  openssl rand -base64 32 | tr '+/' '-_'
}

# --- .env setup ---
if [ ! -f .env ]; then
  cp .env.example .env
  KEY="$(generate_key)"
  if [ "$(uname)" = "Darwin" ]; then
    sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${KEY}|" .env
  else
    sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${KEY}|" .env
  fi
  info "Generated .env with a fresh Fernet encryption key."
else
  warn ".env already exists — keeping it. (Delete it and re-run if you want a fresh setup.)"
fi

# --- Pull + start ---
info "Pulling images from ghcr.io/sbcsp..."
docker compose pull

info "Starting DataMETL..."
docker compose up -d

# Wait briefly for healthchecks to come up
sleep 3

# --- Done ---
PORT="$(grep '^FRONTEND_PORT=' .env | cut -d= -f2 || true)"
PORT="${PORT:-3000}"

echo ""
bold "DataMETL is up."
printf '  \033[36mFrontend\033[0m   http://localhost:%s\n' "$PORT"
printf '  \033[2mInstall dir\033[0m %s\n' "$(pwd)"
echo ""
echo "Stop:    cd $(pwd) && docker compose down"
echo "Update:  cd $(pwd) && docker compose pull && docker compose up -d"
echo "Logs:    cd $(pwd) && docker compose logs -f"
echo ""
