from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    JobEnqueued,
    TapCreate,
    TapRead,
    TapRunRead,
    TapSummary,
    TapTestRequest,
    TapTestResult,
    TapUpdate,
)
from app.crypto import vault
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.connection import Connection
from app.models.scheduled_script import ScheduledScript
from app.models.tap import Tap, TapRun
from app.taps.fetcher import fetch

router = APIRouter(prefix="/api/taps", tags=["taps"])

MASK = "••••••"  # placeholder returned for header/param values; never the real secret


def _redact(tap: Tap) -> TapRead:
    cfg = vault.decrypt(tap.encrypted_config)
    return TapRead(
        id=tap.id,
        name=tap.name,
        url=tap.url,
        method=tap.method,
        records_path=tap.records_path,
        headers={k: MASK for k in (cfg.get("headers") or {})},
        query_params={k: MASK for k in (cfg.get("query_params") or {})},
        has_body=bool(cfg.get("body")),
        dest_connection_ids=[uuid.UUID(c) for c in tap.dest_connection_ids],
        dest_table=tap.dest_table,
        write_mode=tap.write_mode,
        created_at=tap.created_at,
        updated_at=tap.updated_at,
    )


def _merge_secret(provided: dict[str, str], stored: dict[str, str]) -> dict[str, str]:
    """Keep the stored value when the incoming value is still the mask (unchanged); otherwise take
    the new value. Keys absent from `provided` are dropped (removed)."""
    return {k: (stored.get(k, "") if v == MASK else v) for k, v in provided.items()}


def _validate_connections(db: Session, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    found = set(db.execute(select(Connection.id).where(Connection.id.in_(ids))).scalars())
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(404, f"Unknown connection(s): {', '.join(missing)}")


@router.get("", response_model=list[TapSummary])
def list_taps(db: Session = Depends(get_db)) -> list[TapSummary]:
    taps = list(db.execute(select(Tap).order_by(Tap.updated_at.desc())).scalars())
    last_status: dict[uuid.UUID, str] = {}
    last_at: dict[uuid.UUID, datetime] = {}
    for tid, st, at in db.execute(
        select(TapRun.tap_id, TapRun.status, TapRun.started_at)
        .order_by(TapRun.tap_id, TapRun.started_at.desc())
        .distinct(TapRun.tap_id)
    ).all():
        last_status[tid] = st
        last_at[tid] = at

    # Which taps are on a schedule, and is any of those schedules enabled?
    is_scheduled: dict[uuid.UUID, bool] = {}
    schedule_enabled: dict[uuid.UUID, bool] = {}
    for tap_id, enabled in db.execute(
        select(ScheduledScript.tap_id, ScheduledScript.enabled).where(
            ScheduledScript.target_kind == "tap", ScheduledScript.tap_id.is_not(None)
        )
    ).all():
        is_scheduled[tap_id] = True
        schedule_enabled[tap_id] = schedule_enabled.get(tap_id, False) or enabled

    return [
        TapSummary(
            id=t.id,
            name=t.name,
            url=t.url,
            method=t.method,
            dest_count=len(t.dest_connection_ids or []),
            last_run_status=last_status.get(t.id),
            last_run_at=last_at.get(t.id),
            is_scheduled=is_scheduled.get(t.id, False),
            schedule_enabled=schedule_enabled.get(t.id, False),
            updated_at=t.updated_at,
        )
        for t in taps
    ]


@router.post("", response_model=TapRead, status_code=status.HTTP_201_CREATED)
def create_tap(payload: TapCreate, db: Session = Depends(get_db)) -> TapRead:
    _validate_connections(db, payload.dest_connection_ids)
    if payload.dest_connection_ids and not payload.dest_table.strip():
        raise HTTPException(422, "A destination table is required when destinations are selected.")
    cfg = {"headers": payload.headers, "query_params": payload.query_params, "body": payload.body}
    tap = Tap(
        name=payload.name,
        url=payload.url,
        method=payload.method,
        records_path=payload.records_path,
        dest_connection_ids=[str(c) for c in payload.dest_connection_ids],
        dest_table=payload.dest_table,
        write_mode=payload.write_mode,
        encrypted_config=vault.encrypt(cfg),
    )
    db.add(tap)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A tap with that name already exists") from e
    db.refresh(tap)
    return _redact(tap)


@router.post("/test", response_model=TapTestResult)
async def test_tap(payload: TapTestRequest) -> TapTestResult:
    """Fetch the endpoint and return a sample WITHOUT saving anything — used by the editor to see
    the response structure. Errors come back in the body (not as 5xx) so the UI can show them."""
    try:
        res = await fetch(
            url=payload.url, method=payload.method, headers=payload.headers,
            query_params=payload.query_params, body=payload.body, records_path=payload.records_path,
        )
    except Exception as e:
        return TapTestResult(ok=False, error=str(getattr(e, "__cause__", None) or e))
    records = res["records"]
    return TapTestResult(
        ok=True, http_status=res["http_status"], record_count=len(records), sample=records[:20]
    )


@router.get("/{tap_id}", response_model=TapRead)
def get_tap(tap_id: uuid.UUID, db: Session = Depends(get_db)) -> TapRead:
    tap = db.get(Tap, tap_id)
    if tap is None:
        raise HTTPException(404, "Tap not found")
    return _redact(tap)


@router.put("/{tap_id}", response_model=TapRead)
def update_tap(tap_id: uuid.UUID, payload: TapUpdate, db: Session = Depends(get_db)) -> TapRead:
    tap = db.get(Tap, tap_id)
    if tap is None:
        raise HTTPException(404, "Tap not found")

    if payload.dest_connection_ids is not None:
        _validate_connections(db, payload.dest_connection_ids)
        tap.dest_connection_ids = [str(c) for c in payload.dest_connection_ids]
    if payload.name is not None:
        tap.name = payload.name
    if payload.url is not None:
        tap.url = payload.url
    if payload.method is not None:
        tap.method = payload.method
    if payload.records_path is not None:
        tap.records_path = payload.records_path
    if payload.dest_table is not None:
        tap.dest_table = payload.dest_table
    if payload.write_mode is not None:
        tap.write_mode = payload.write_mode

    # Merge secret config — keep unchanged (masked) values, apply real edits.
    cfg = vault.decrypt(tap.encrypted_config)
    if payload.headers is not None:
        cfg["headers"] = _merge_secret(payload.headers, cfg.get("headers") or {})
    if payload.query_params is not None:
        cfg["query_params"] = _merge_secret(payload.query_params, cfg.get("query_params") or {})
    if payload.body is not None:
        cfg["body"] = payload.body
    tap.encrypted_config = vault.encrypt(cfg)

    if tap.dest_connection_ids and not (tap.dest_table or "").strip():
        raise HTTPException(422, "A destination table is required when destinations are selected.")
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "A tap with that name already exists") from e
    db.refresh(tap)
    return _redact(tap)


@router.delete("/{tap_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tap(tap_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    tap = db.get(Tap, tap_id)
    if tap is None:
        raise HTTPException(404, "Tap not found")
    db.delete(tap)
    db.commit()


@router.post("/{tap_id}/fetch", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def fetch_now(tap_id: uuid.UUID, db: Session = Depends(get_db)) -> JobEnqueued:
    if db.get(Tap, tap_id) is None:
        raise HTTPException(404, "Tap not found")
    job_id = await enqueue("fetch_tap", str(tap_id))
    return JobEnqueued(job_id=job_id)


@router.get("/{tap_id}/runs", response_model=list[TapRunRead])
def list_tap_runs(tap_id: uuid.UUID, limit: int = 25, db: Session = Depends(get_db)) -> list[TapRun]:
    if db.get(Tap, tap_id) is None:
        raise HTTPException(404, "Tap not found")
    return list(
        db.execute(
            select(TapRun)
            .where(TapRun.tap_id == tap_id)
            .order_by(TapRun.started_at.desc())
            .limit(max(1, min(limit, 200)))
        ).scalars()
    )
