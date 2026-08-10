"""Run the Rekor outbox processor as a standalone process.

Usage: ./venv/bin/python -m app.audit_worker
With no REKOR_URL it stays idle, preserving local-only audit events.
"""
from __future__ import annotations
import os, time
from app.core.db import SessionLocal
from app.services.rekor import process_once

def main() -> None:
    interval = max(5, int(os.getenv("REKOR_WORKER_INTERVAL", "30")))
    while True:
        db = SessionLocal()
        try:
            processed = process_once(db)
            if processed:
                print(f"[audit-worker] anchored {processed} event(s)", flush=True)
        except Exception as exc:
            db.rollback()
            print(f"[audit-worker] cycle failed: {exc}", flush=True)
        finally:
            db.close()
        time.sleep(interval)

if __name__ == "__main__":
    main()
