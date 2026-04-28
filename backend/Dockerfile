# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# System deps (libpq for psycopg) + uv via pip (avoids ghcr.io auth issues)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir 'uv>=0.5,<0.6'

# --- deps layer (cached unless pyproject/lock changes) ---
COPY pyproject.toml ./
COPY uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project 2>/dev/null || \
    uv sync --no-install-project

# --- app layer ---
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen 2>/dev/null || uv sync

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
