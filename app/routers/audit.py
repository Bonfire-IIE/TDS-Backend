from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.audit import AuditEvent
from app.services.audit import evidence

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/events")
def list_events(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)).scalars().all()
    return {"code": 0, "message": "ok", "data": [{"event_id": r.event_id, "event_type": r.event_type, "stream_id": r.stream_id, "sequence": r.sequence, "resource_type": r.resource_type, "resource_id": r.resource_id, "current_hash": r.current_hash, "occurred_at": r.occurred_at} for r in rows]}

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
