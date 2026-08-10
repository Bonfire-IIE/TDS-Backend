"""统一审计事件服务：事务内写本地链，Rekor 由 outbox 异步处理。"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.audit import AuditEvent, AuditOutbox, AuditAnchor

def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def append(db: Session, *, event_type: str, stream_id: str, payload: dict, actor: dict | None = None, resource_type: str | None = None, resource_id: str | None = None) -> AuditEvent:
    last = db.execute(select(AuditEvent).where(AuditEvent.stream_id == stream_id).order_by(AuditEvent.sequence.desc()).with_for_update()).scalars().first()
    sequence = (last.sequence + 1) if last else 1
    previous = last.current_hash if last else ""
    event_id = str(uuid.uuid4())
    occurred = datetime.now(timezone.utc)
    envelope = {"schema_version": "1.0", "event_id": event_id, "event_type": event_type, "stream_id": stream_id, "sequence": sequence, "actor": actor, "resource_type": resource_type, "resource_id": resource_id, "payload": payload, "occurred_at": occurred.isoformat()}
    payload_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    current = hashlib.sha256(f"{stream_id}:{sequence}:{previous}:{payload_hash}".encode()).hexdigest()
    row = AuditEvent(id=event_id, event_id=event_id, event_type=event_type, stream_id=stream_id, sequence=sequence, actor=actor, resource_type=resource_type, resource_id=resource_id, payload=envelope, payload_hash=payload_hash, previous_hash=previous, current_hash=current, occurred_at=occurred)
    db.add(row)
    db.add(AuditOutbox(id=str(uuid.uuid4()), event_id=event_id, status="pending"))
    db.flush()
    return row

def evidence(db: Session, event_id: str) -> dict | None:
    event = db.execute(select(AuditEvent).where(AuditEvent.event_id == event_id)).scalar_one_or_none()
    if not event: return None
    anchor = db.execute(select(AuditAnchor).where(AuditAnchor.event_id == event_id)).scalar_one_or_none()
    return {"event": event.payload, "payload_hash": event.payload_hash, "previous_hash": event.previous_hash, "current_hash": event.current_hash, "anchor": {"provider": anchor.provider, "rekor_uuid": anchor.rekor_uuid, "log_index": anchor.log_index, "integrated_time": anchor.integrated_time, "entry_body": anchor.entry_body, "inclusion_proof": anchor.inclusion_proof, "checkpoint": anchor.checkpoint, "verification_status": anchor.verification_status} if anchor else None, "status": anchor.verification_status if anchor else "local_only"}
