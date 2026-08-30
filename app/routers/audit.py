from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.audit import AuditEvent
from app.models.project import Project
from app.services.audit import evidence

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/events")
def list_events(
    contract_id: str | None = Query(None, max_length=128),
    project_id: str | None = Query(None, max_length=64),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Query audit evidence while preserving the contract-stream chain model.

    Project events share their contract's hash stream, so a project lookup first
    resolves the project to its contract and then returns that complete chain.
    """
    normalized_contract = (contract_id or "").strip()
    normalized_project = (project_id or "").strip()
    if normalized_project:
        project = db.get(Project, normalized_project)
        if not project:
            return {"code": 0, "message": "ok", "data": []}
        if normalized_contract and normalized_contract != project.contract_id:
            return {"code": 0, "message": "ok", "data": []}
        normalized_contract = project.contract_id

    stmt = select(AuditEvent)
    if normalized_contract:
        stmt = stmt.where(AuditEvent.stream_id == f"contract:{normalized_contract}")
    rows = db.execute(stmt.order_by(AuditEvent.created_at.desc()).limit(1000)).scalars().all()

    def item(row: AuditEvent) -> dict:
        envelope = row.payload or {}
        payload = envelope.get("payload") if isinstance(envelope, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        return {
            "event_id": row.event_id, "event_type": row.event_type,
            "stream_id": row.stream_id, "sequence": row.sequence,
            "resource_type": row.resource_type, "resource_id": row.resource_id,
            "contract_id": payload.get("contract_id"),
            "project_id": payload.get("project_id"),
            "current_hash": row.current_hash, "occurred_at": row.occurred_at,
        }

    return {"code": 0, "message": "ok", "data": [item(row) for row in rows]}

@router.get("/events/{event_id}/evidence")
def get_evidence(event_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    data = evidence(db, event_id)
    if not data: raise HTTPException(404, "审计事件不存在")
    return {"code": 0, "message": "ok", "data": data}

@router.get("/sync")
def sync_events(connector_id: str = Query(...), cursor: str | None = Query(None), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Incremental evidence mirror feed; only events tied to this connector are returned."""
    rows = db.execute(select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.event_id).limit(1000)).scalars().all()
    out = []
    for row in rows:
        if cursor and f"{row.created_at.isoformat()}|{row.event_id}" <= cursor:
            continue
        blob = row.payload or {}
        actor = row.actor or {}
        text = str(blob)
        if connector_id not in text and actor.get("connector_id") != connector_id:
            continue
        item = evidence(db, row.event_id)
        if item:
            item["event_id"] = row.event_id
            item["created_at"] = row.created_at
            out.append(item)
    next_cursor = cursor
    if out:
        last = rows[-1]
        next_cursor = f"{last.created_at.isoformat()}|{last.event_id}"
    return {"code": 0, "message": "ok", "data": {"events": out, "next_cursor": next_cursor, "count": len(out)}}
