"""Rekor outbox adapter. Endpoint is optional; absent endpoint means local-only mode."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json, uuid, base64, hashlib
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.audit import AuditEvent, AuditOutbox, AuditAnchor
from app.core.config import settings

def _normalize_entry(result: object, response: httpx.Response | None = None) -> tuple[str | None, dict]:
    """Rekor v1 returns {uuid: {body, logIndex, ...}}, not {entry: ...}."""
    if isinstance(result, dict) and "entry" in result and isinstance(result["entry"], dict):
        result = result["entry"]
    if isinstance(result, dict) and len(result) == 1:
        key, value = next(iter(result.items()))
        # Rekor may omit the integrated fields from the create response while
        # Trillian integration catches up. The UUID-keyed envelope is still
        # the entry shape and can later be completed through GET by UUID.
        if isinstance(value, dict):
            return key, value
    value = result if isinstance(result, dict) else {}
    return (response.headers.get("ETag") if response is not None else None), value

def process_once(db: Session, limit: int = 20) -> int:
    endpoint = settings.rekor_url.rstrip("/")
    if not endpoint:
        return 0
    rows = db.execute(select(AuditOutbox).where(AuditOutbox.status.in_(["pending", "retrying"]), (AuditOutbox.next_retry_at.is_(None)) | (AuditOutbox.next_retry_at <= datetime.now(timezone.utc))).order_by(AuditOutbox.created_at).limit(limit).with_for_update(skip_locked=True)).scalars().all()
    key = ec.generate_private_key(ec.SECP256R1())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    done = 0
    for outbox in rows:
        event = db.execute(select(AuditEvent).where(AuditEvent.event_id == outbox.event_id)).scalar_one_or_none()
        if not event: outbox.status = "dead_letter"; outbox.last_error = "audit event missing"; continue
        outbox.status = "submitting"; outbox.attempts += 1
        body = {"event_id": event.event_id, "event_type": event.event_type, "stream_id": event.stream_id, "sequence": event.sequence, "payload_hash": event.payload_hash, "previous_hash": event.previous_hash, "current_hash": event.current_hash, "occurred_at": event.occurred_at.isoformat()}
        try:
            # Rekor hashedrekord requires a detached ECDSA signature, public key, and SHA256 content.
            content = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            signature = key.sign(content, ec.ECDSA(hashes.SHA256()))
            proposed = {"apiVersion": "0.0.1", "kind": "hashedrekord", "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": hashlib.sha256(content).hexdigest()}},
                "signature": {"content": base64.b64encode(signature).decode(), "publicKey": {"content": base64.b64encode(public_pem).decode()}},
            }}
            response = httpx.post(f"{endpoint}/api/v1/log/entries", json=proposed, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            anchor_uuid, entry = _normalize_entry(result, response)
            verification = entry.get("verification") or {}
            proof = verification.get("inclusionProof") or {}
            db.merge(AuditAnchor(id=str(uuid.uuid4()), event_id=event.event_id, provider="rekor", rekor_uuid=anchor_uuid, log_index=entry.get("logIndex"), integrated_time=entry.get("integratedTime"), inclusion_proof=proof, checkpoint={"signed_entry_timestamp": verification.get("signedEntryTimestamp"), "checkpoint": proof.get("checkpoint")}, entry_body=json.dumps(result, ensure_ascii=False), verification_status="submitted", submitted_at=datetime.now(timezone.utc)))
            outbox.status = "submitted"; outbox.last_error = None; done += 1
        except Exception as exc:
            outbox.status = "retrying" if outbox.attempts < 20 else "dead_letter"
            outbox.last_error = str(exc)[:2000]
            outbox.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 2 ** min(outbox.attempts, 10)))
    db.commit()
    return done
