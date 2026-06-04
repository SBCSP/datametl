from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas_io import McpActivateRequest, McpActiveResponse
from app.db import get_db
from app.mcp.state import clear_active, get_active_connection, set_active

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/active", response_model=McpActiveResponse | None)
def get_active(db: Session = Depends(get_db)) -> McpActiveResponse | None:
    conn = get_active_connection(db)
    if conn is None:
        return None
    return McpActiveResponse(connection_id=conn.id, name=conn.name, engine=conn.engine)


@router.post("/activate", response_model=McpActiveResponse)
def activate(payload: McpActivateRequest, db: Session = Depends(get_db)) -> McpActiveResponse:
    """Make a connection the sole active read-only MCP target (replaces any current one)."""
    try:
        conn = set_active(db, payload.connection_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return McpActiveResponse(connection_id=conn.id, name=conn.name, engine=conn.engine)


@router.post("/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate(db: Session = Depends(get_db)) -> None:
    clear_active(db)
