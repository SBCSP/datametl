COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env
COMPOSE_SAMPLES := $(COMPOSE) -f infra/docker-compose.samples.yml --profile samples

.PHONY: help up up-samples urls down logs ps build rebuild migrate revision shell-backend shell-db psql redis-cli test lint typecheck fmt clean key release deploy-up deploy-down deploy-build-local

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
	@echo "  make release v=v0.X.Y   Tag + push, triggering the release workflow on GitHub"
	@echo "  make deploy-up          Run the deploy compose locally against published GHCR images"
	@echo "  make deploy-down        Stop the deploy stack"
	@echo "  make deploy-build-local Build the prod images locally (skips GHCR) for smoke tests"

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
	@git diff --quiet || { echo "Working tree has uncommitted changes."; exit 1; }
	git tag -a $(v) -m "Release $(v)"
	git push origin $(v)
	@echo ""
	@echo "Tag $(v) pushed. The release workflow is now building images and attaching"
	@echo "release assets. Watch progress at:"
	@echo "  https://github.com/sbcsp/datametl/actions"

# Run the deploy compose locally (against the published GHCR images) — useful for testing
# what end users get after running install.sh.
deploy-up:
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy up -d --pull always

deploy-down:
	docker compose -f infra/docker-compose.deploy.yml --env-file .env.deploy down

# Build the prod images locally with the current source tree (skips GHCR). Useful for
# smoke-testing the multi-stage Dockerfile changes before tagging a release.
deploy-build-local:
	docker build -t ghcr.io/sbcsp/datametl-backend:dev backend/
	docker build --target prod -t ghcr.io/sbcsp/datametl-frontend:dev frontend/
	@echo ""
	@echo "Built ghcr.io/sbcsp/datametl-{backend,frontend}:dev. To run with these:"
	@echo "  DATAMETL_VERSION=dev make deploy-up"
