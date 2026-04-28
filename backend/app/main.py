from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    activity,
    comparisons,
    connections,
    jobs,
    mappings,
    migrations,
    settings as settings_api,
    snapshots,
    verifications,
)
from app.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="DataMETL",
    description="Local-first data migration tool — schema introspection, comparison, and mapping API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router)
app.include_router(snapshots.router)
app.include_router(comparisons.router)
app.include_router(mappings.router)
app.include_router(migrations.router)
app.include_router(verifications.router)
app.include_router(activity.router)
app.include_router(settings_api.router)
app.include_router(jobs.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
