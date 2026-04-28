from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas_io import JobStatusResponse
from app.jobs.queue import status as job_status

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    try:
        info = await job_status(job_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Job lookup failed: {e}") from e
    return JobStatusResponse(**info)
