COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env
COMPOSE_SAMPLES := $(COMPOSE) -f infra/docker-compose.samples.yml --profile samples

.PHONY: help up up-samples urls down logs ps build rebuild migrate revision shell-backend shell-db psql redis-cli test lint typecheck fmt clean key release deploy-up deploy-pull deploy-down deploy-build-local

help:
	@echo "DataMETL — common commands"
	@echo "  make key            Generate a Fernet encryption key (paste into .env)"
	@echo "  make up             Build (if needed) and start app stack"
	@echo "  make up-samples     Build (if needed) and start app stack + sample source/dest databases"
	@echo "  make urls           Print the localhost URLs for the running stack"
	@echo "  make down           Stop everything (volumes preserved)"
	@echo "  make logs           Tail logs from all services"
	@echo "  make ps             List running services"
	@echo "  make build          Build all images"
	@echo "  make rebuild        Rebuild images with --no-cache"
	@echo "  make migrate        Run alembic upgrade head against app DB"
	@echo "  make revision m=... Create a new alembic revision (autogenerate)"
	@echo "  make shell-backend  Open a shell in the backend container"
	@echo "  make psql           psql into the app metadata DB"
	@echo "  make test           Run backend pytest"
	@echo "  make lint           Run ruff on backend"
	@echo "  make typecheck      Run mypy on backend"
	@echo "  make fmt            Run ruff format on backend"
	@echo ""
	@echo "Release / deploy"
	@echo "  make release v=v0.X.Y    Tag + push, triggering the release workflow on GitHub"
	@echo "  make deploy-build-local  Build prod images locally (tagged :dev) for smoke tests"
	@echo "  make deploy-up           Start the deploy compose (auto-generates .env.deploy)"
	@echo "  make deploy-pull         Force-pull latest published images + restart"
	@echo "  make deploy-down         Stop the deploy stack"

key:
	@python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

up:
	@$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory urls

up-samples:
	@$(COMPOSE_SAMPLES) up -d --build
	@$(MAKE) --no-print-directory urls SAMPLES=1

urls:
	@printf '\n\033[1mDataMETL is up.\033[0m\n'
	@printf '  \033[36mFrontend\033[0m         http://localhost:3000\n'
	@printf '  \033[36mAPI (OpenAPI)\033[0m    http://localhost:8000/docs\n'
	@printf '  \033[36mAPI health\033[0m       http://localhost:8000/health\n'
	@printf '  \033[2mApp metadata DB\033[0m  postgres://datametl:datametl@localhost:5433/datametl\n'
	@printf '  \033[2mRedis\033[0m            redis://localhost:6379\n'
ifeq ($(SAMPLES),1)
	@printf '  \033[2mSample source\033[0m    postgres://postgres:samplesource@localhost:5500/source  (Supabase-flavored)\n'
	@printf '  \033[2mSample dest\033[0m      postgres://postgres:sampledest@localhost:5501/dest      (vanilla)\n'
	@printf '  \033[33mNote:\033[0m when adding these in the UI, use host \033[1msample-source\033[0m / \033[1msample-dest\033[0m and port \033[1m5432\033[0m (compose network names).\n'
endif
	@printf '\nTail logs with \033[1mmake logs\033[0m, stop with \033[1mmake down\033[0m.\n\n'

down:
	$(COMPOSE_SAMPLES) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

rebuild:
	$(COMPOSE) build --no-cache

migrate:
	$(COMPOSE) run --rm backend alembic upgrade head

revision:
	$(COMPOSE) run --rm backend alembic revision --autogenerate -m "$(m)"

shell-backend:
	$(COMPOSE) exec backend /bin/sh

psql:
	$(COMPOSE) exec app-postgres psql -U $${APP_DB_USER:-datametl} -d $${APP_DB_NAME:-datametl}

redis-cli:
	$(COMPOSE) exec redis redis-cli

test:
	$(COMPOSE) run --rm backend pytest

lint:
	$(COMPOSE) run --rm backend ruff check .

typecheck:
	$(COMPOSE) run --rm backend mypy app

fmt:
	$(COMPOSE) run --rm backend ruff format .

clean:
	$(COMPOSE_SAMPLES) down -v

# --- Release / deploy helpers ---

# Cut a release: tags HEAD with `v=...` and pushes the tag, which triggers the GitHub
# Actions workflow at .github/workflows/release.yml. Use:
#   make release v=v0.2.1
release:
ifndef v
	$(error v is required, e.g. make release v=v0.2.1)
endif
	@if [ "$$(echo $(v) | cut -c1)" != "v" ]; then \
		echo "Tag must start with 'v', e.g. v0.2.1"; exit 1; \
	fi
	@# Reject if there are uncommitted OR untracked changes. `git status --porcelain`
	@# returns one line per file in either state — empty output means clean tree. (The
	@# previous `git diff --quiet` only caught modified-tracked files, which let an
	@# untracked file slip through and cause a CI build failure.)
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Working tree has uncommitted or untracked changes:"; \
		git status --short; \
		echo ""; \
		echo "Commit (or .gitignore) everything before releasing."; \
		exit 1; \
	fi
	@# Make sure backend/app/api/settings.py::_VERSION matches the tag we're cutting.
	@TAG_VERSION="$$(echo $(v) | sed 's/^v//')"; \
	  CODE_VERSION="$$(grep '^_VERSION' backend/app/api/settings.py | sed -E 's/^_VERSION[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"; \
	  if [ "$$TAG_VERSION" != "$$CODE_VERSION" ]; then \
	    echo "Version mismatch: backend/app/api/settings.py has _VERSION = \"$$CODE_VERSION\""; \
	    echo "but you're tagging $(v) (== $$TAG_VERSION)."; \
	    echo "Bump _VERSION first, commit, then re-run."; \
	    exit 1; \
	  fi
	git tag -a $(v) -m "Release $(v)"
	git push origin $(v)
	@echo ""
	@echo "Tag $(v) pushed. The release workflow is now building images and attaching"
	@echo "release assets. Watch progress at:"
	@echo "  https://github.com/sbcsp/datametl/actions"

# Run the deploy compose locally — for testing what end users will get from install.sh.
# Auto-generates .env.deploy on first run (with a fresh Fernet key) so you don't get
# stuck on "ENCRYPTION_KEY not valid" the first time you run.
#
# We deliberately do NOT pass --pull always: when smoke-testing locally with :dev images
# built via `make deploy-build-local`, those images aren't on the registry yet and a
# forced pull would fail. For pulling published versions, use `make deploy-pull`.
deploy-up: .env.deploy
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy up -d

# Force-pull the newest published images from GHCR + restart. Useful after a release.
deploy-pull: .env.deploy
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy pull
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy up -d

deploy-down:
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy down

# First-run helper: copy the example and inject a freshly-generated Fernet key. Same
# operation install.sh does for end users.
.env.deploy: .env.deploy.example
	@cp .env.deploy.example .env.deploy
	@KEY=$$(openssl rand -base64 32 | tr '+/' '-_'); \
	  if [ "$$(uname)" = "Darwin" ]; then \
	    sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" .env.deploy; \
	  else \
	    sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" .env.deploy; \
	  fi
	@echo "Created .env.deploy with a fresh ENCRYPTION_KEY."

# Build the prod images locally from the current source tree (skips GHCR). Tags them as
# :dev so deploy-up picks them up via DATAMETL_VERSION=dev.
deploy-build-local:
	docker build -t ghcr.io/sbcsp/datametl-backend:dev backend/
	docker build --target prod -t ghcr.io/sbcsp/datametl-frontend:dev frontend/
	@echo ""
	@echo "Built ghcr.io/sbcsp/datametl-{backend,frontend}:dev. To run with these:"
	@echo "  DATAMETL_VERSION=dev make deploy-up"
