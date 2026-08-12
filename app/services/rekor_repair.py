"""Backfill missing Rekor receipt fields for anchors created by older adapters."""
from __future__ import annotations
import os
from app.core.config import settings
import httpx
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.audit import AuditAnchor
from app.services.rekor import _normalize_entry

def main():
    endpoint = settings.rekor_url.rstrip("/")
    if not endpoint: raise SystemExit("REKOR_URL is required")
    with SessionLocal() as db:
        rows = db.execute(select(AuditAnchor).where(AuditAnchor.provider == "rekor", AuditAnchor.log_index.is_(None))).scalars().all()
        repaired = 0
        for row in rows:
            if not row.rekor_uuid: continue
            response = httpx.get(f"{endpoint}/api/v1/log/entries/{row.rekor_uuid}", timeout=10.0)
            response.raise_for_status()
            uuid_value, entry = _normalize_entry(response.json(), response)
            if entry.get("logIndex") is None:
                continue
            verification = entry.get("verification") or {}; proof = verification.get("inclusionProof") or {}
            row.rekor_uuid = uuid_value or row.rekor_uuid
            row.log_index = entry.get("logIndex"); row.integrated_time = entry.get("integratedTime")
            row.inclusion_proof = proof
            row.checkpoint = {"signed_entry_timestamp": verification.get("signedEntryTimestamp"), "checkpoint": proof.get("checkpoint")}
            row.entry_body = response.text
            row.verification_status = "submitted"
            repaired += 1
        db.commit(); print(f"repaired {repaired} anchor(s)")

if __name__ == "__main__": main()
