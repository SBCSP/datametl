# Repo-root paths so targets work even if make is invoked with -C / another cwd.
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_FILE := $(ROOT)/.env
COMPOSE := $(ROOT)/scripts/dev-compose.sh
COMPOSE_SAMPLES := $(COMPOSE) -f $(ROOT)/infra/docker-compose.samples.yml --profile samples
COMPOSE_ENGINES := $(COMPOSE) -f $(ROOT)/infra/docker-compose.engines.yml
COMPOSE_ALL := $(COMPOSE) -f $(ROOT)/infra/docker-compose.samples.yml -f $(ROOT)/infra/docker-compose.engines.yml --profile samples --profile mysql --profile mssql --profile engines

.PHONY: help ensure-env up up-samples up-mysql up-mssql up-engines urls db-urls down logs ps build rebuild migrate revision shell-backend shell-db psql redis-cli test lint typecheck fmt clean key release deploy-up deploy-pull deploy-down deploy-build-local

help:
	@echo "DataMETL — common commands"
	@echo "  make key            Generate a Fernet encryption key (paste into .env)"
	@echo "  make ensure-env     Create .env from example if missing (sets ENCRYPTION_KEY)"
	@echo "  make up             Build (if needed) and start app stack"
	@echo "  make up-samples     Build (if needed) and start app stack + sample source/dest databases"
	@echo "  make up-mysql       Start MySQL test engine (profile mysql; host port 3307)"
	@echo "  make up-mssql       Start SQL Server test engine (profile mssql; host port 14333)"
	@echo "  make up-engines     Start MySQL + SQL Server test engines together"
	@echo "  make urls           Print the localhost URLs for the running stack"
	@echo "  make db-urls        Print connection hints for sample + engine test DBs"
	@echo "  make down           Stop everything including samples/engines (volumes preserved)"
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
	@python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
	  || python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Create .env from the example if needed, and refuse a placeholder ENCRYPTION_KEY.
ensure-env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
	  cp "$(ROOT)/.env.example" "$(ENV_FILE)"; \
	  KEY=$$( $(MAKE) --no-print-directory key ); \
	  if [ "$$(uname)" = "Darwin" ]; then \
	    sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" "$(ENV_FILE)"; \
	  else \
	    sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" "$(ENV_FILE)"; \
	  fi; \
	  echo "Created $(ENV_FILE) with a fresh ENCRYPTION_KEY."; \
	  echo "Edit AUTH_* / other settings as needed, then re-run make up."; \
	fi
	@if grep -qE '^ENCRYPTION_KEY=(CHANGE_ME_GENERATE_A_FERNET_KEY)?[[:space:]]*$$' "$(ENV_FILE)"; then \
	  echo "ENCRYPTION_KEY in $(ENV_FILE) is missing or still a placeholder."; \
	  echo "Run: make key   then paste into .env"; \
	  exit 1; \
	fi

up: ensure-env
	@$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory urls

up-samples: ensure-env
	@$(COMPOSE_SAMPLES) up -d --build
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory urls SAMPLES=1

up-mysql: ensure-env
	@$(COMPOSE_ENGINES) --profile mysql up -d
	@$(MAKE) --no-print-directory db-urls MYSQL=1

up-mssql: ensure-env
	@$(COMPOSE_ENGINES) --profile mssql up -d
	@$(MAKE) --no-print-directory db-urls MSSQL=1

up-engines: ensure-env
	@$(COMPOSE_ENGINES) --profile engines up -d
	@$(MAKE) --no-print-directory db-urls MYSQL=1 MSSQL=1

urls:
	@printf '\n\033[1mDataMETL is up.\033[0m\n'
	@printf '  \033[36mFrontend\033[0m         http://localhost:3005\n'
	@printf '  \033[36mAPI (OpenAPI)\033[0m    http://localhost:8001/docs\n'
	@printf '  \033[36mAPI health\033[0m       http://localhost:8001/health\n'
	@printf '  \033[2mApp metadata DB\033[0m  postgres://datametl:datametl@localhost:5433/datametl\n'
	@printf '  \033[2mRedis\033[0m            redis://localhost:6380\n'
ifeq ($(SAMPLES),1)
	@printf '  \033[2mSample source\033[0m    postgres://postgres:samplesource@localhost:5500/source  (Supabase-flavored)\n'
	@printf '  \033[2mSample dest\033[0m      postgres://postgres:sampledest@localhost:5501/dest      (vanilla)\n'
	@printf '  \033[33mNote:\033[0m when adding these in the UI, use host \033[1msample-source\033[0m / \033[1msample-dest\033[0m and port \033[1m5432\033[0m (compose network names).\n'
endif
ifeq ($(MYSQL),1)
	@printf '  \033[2mEngine MySQL\033[0m     mysql://root:$${ENGINE_MYSQL_PASSWORD:-EngineMySQL_ChangeMe!}@localhost:3307/$${ENGINE_MYSQL_DATABASE:-testdb}\n'
	@printf '  \033[33mNote:\033[0m in the UI use host \033[1mengine-mysql\033[0m port \033[1m3306\033[0m user \033[1mroot\033[0m.\n'
endif
ifeq ($(MSSQL),1)
	@printf '  \033[2mEngine SQL Server\033[0m  mssql://sa:$${ENGINE_MSSQL_PASSWORD:-EngineMSSQL_ChangeMe1!}@localhost:14333/master\n'
	@printf '  \033[33mNote:\033[0m in the UI use host \033[1mengine-mssql\033[0m port \033[1m1433\033[0m user \033[1msa\033[0m database \033[1mmaster\033[0m (or create a DB).\n'
endif
	@printf '\nTail logs with \033[1mmake logs\033[0m, stop with \033[1mmake down\033[0m.\n\n'

db-urls:
	@printf '\n\033[1mTest database connection hints\033[0m\n'
	@printf '  \033[2mSample source\033[0m    postgres://postgres:$${SAMPLE_SOURCE_PASSWORD:-samplesource}@localhost:5500/source\n'
	@printf '                   UI: host \033[1msample-source\033[0m port \033[1m5432\033[0m\n'
	@printf '  \033[2mSample dest\033[0m      postgres://postgres:$${SAMPLE_DEST_PASSWORD:-sampledest}@localhost:5501/dest\n'
	@printf '                   UI: host \033[1msample-dest\033[0m port \033[1m5432\033[0m\n'
	@printf '  \033[2mEngine MySQL\033[0m     mysql://root:$${ENGINE_MYSQL_PASSWORD:-EngineMySQL_ChangeMe!}@localhost:3307/$${ENGINE_MYSQL_DATABASE:-testdb}\n'
	@printf '                   UI: host \033[1mengine-mysql\033[0m port \033[1m3306\033[0m user \033[1mroot\033[0m\n'
	@printf '  \033[2mEngine SQL Server\033[0m  mssql://sa:$${ENGINE_MSSQL_PASSWORD:-EngineMSSQL_ChangeMe1!}@localhost:14333/master\n'
	@printf '                   UI: host \033[1mengine-mssql\033[0m port \033[1m1433\033[0m user \033[1msa\033[0m\n'
	@printf '\n'

down:
	$(COMPOSE_ALL) down

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
	$(COMPOSE_ALL) down -v

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
	  DBPASS=$$(openssl rand -hex 24); \
	  if [ "$$(uname)" = "Darwin" ]; then \
	    sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" .env.deploy; \
	    sed -i '' "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=$$DBPASS|" .env.deploy; \
	  else \
	    sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$KEY|" .env.deploy; \
	    sed -i "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=$$DBPASS|" .env.deploy; \
	  fi
	@echo "Created .env.deploy with a fresh ENCRYPTION_KEY and strong APP_DB_PASSWORD."

# Build the prod images locally from the current source tree (skips GHCR). Tags them as
# :dev so deploy-up picks them up via DATAMETL_VERSION=dev.
deploy-build-local:
	docker build -t ghcr.io/sbcsp/datametl-backend:dev backend/
	docker build --target prod -t ghcr.io/sbcsp/datametl-frontend:dev frontend/
	@echo ""
	@echo "Built ghcr.io/sbcsp/datametl-{backend,frontend}:dev. To run with these:"
	@echo "  DATAMETL_VERSION=dev make deploy-up"
