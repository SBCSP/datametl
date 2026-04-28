from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas_io import (
    ConnectionCreate,
    ConnectionDetail,
    ConnectionRead,
    ConnectionUpdate,
    JobEnqueued,
    RedactedPostgresCredentials,
    TestConnectionResult,
)
from app.connectors import for_engine
from app.crypto import vault
from app.db import get_db
from app.jobs.queue import enqueue
from app.models.connection import Connection

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _redact(creds: dict) -> RedactedPostgresCredentials:
    """Strip secret fields. Used by the GET endpoint so the edit form can pre-fill."""
    return RedactedPostgresCredentials(
        host=creds.get("host", ""),
        port=int(creds.get("port", 5432)),
        database=creds.get("database", ""),
        user=creds.get("user", ""),
        sslmode=creds.get("sslmode"),
        has_sslrootcert=bool(creds.get("sslrootcert")),
    )


@router.get("", response_model=list[ConnectionRead])
def list_connections(db: Session = Depends(get_db)) -> list[Connection]:
    return list(db.execute(select(Connection).order_by(Connection.created_at.desc())).scalars())


@router.post("", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db)) -> Connection:
    conn = Connection(
        name=payload.name,
        engine=payload.engine,
        encrypted_credentials=vault.encrypt(payload.credentials.model_dump()),
    )
    db.add(conn)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="A connection with that name already exists") from e
    db.refresh(conn)
    return conn


@router.get("/{connection_id}", response_model=ConnectionDetail)
def get_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)) -> ConnectionDetail:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    creds = vault.decrypt(conn.encrypted_credentials)
    return ConnectionDetail(
        id=conn.id,
        name=conn.name,
        engine=conn.engine,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
        redacted_credentials=_redact(creds),
    )


@router.put("/{connection_id}", response_model=ConnectionDetail)
def update_connection(
    connection_id: uuid.UUID, payload: ConnectionUpdate, db: Session = Depends(get_db)
) -> ConnectionDetail:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    if payload.name is not None:
        conn.name = payload.name
    if payload.credentials is not None:
        # Merge: only fields explicitly set in the update payload are replaced; everything
        # else (including password and sslrootcert) keeps its previous value. This lets the
        # frontend update host/port/user/sslmode without re-prompting for the password.
        existing = vault.decrypt(conn.encrypted_credentials)
        updates = payload.credentials.model_dump(exclude_unset=True)
        merged = {**existing, **updates}
        conn.encrypted_credentials = vault.encrypt(merged)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="A connection with that name already exists") from e
    db.refresh(conn)
    creds = vault.decrypt(conn.encrypted_credentials)
    return ConnectionDetail(
        id=conn.id,
        name=conn.name,
        engine=conn.engine,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
        redacted_credentials=_redact(creds),
    )


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    db.delete(conn)
    db.commit()


@router.post("/{connection_id}/test", response_model=TestConnectionResult)
def test_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)) -> TestConnectionResult:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    creds = vault.decrypt(conn.encrypted_credentials)
    result = for_engine(conn.engine, creds).test_connection()
    return TestConnectionResult(ok=result.ok, detail=result.detail)


@router.post("/{connection_id}/introspect", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def introspect_connection(connection_id: uuid.UUID, db: Session = Depends(get_db)) -> JobEnqueued:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    job_id = await enqueue("introspect_connection", str(connection_id))
    return JobEnqueued(job_id=job_id)
