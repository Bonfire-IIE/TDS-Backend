"""PostgreSQL session advisory locks for execution idempotency.

Usage-control methods commit during reservation, so transaction-scoped locks are insufficient.
The session lock survives commits and covers all external Kuscia side effects.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


def _lock_id(scope: str, key: str) -> int:
    raw = hashlib.sha256(f"{scope}:{key}".encode()).digest()[:8]
    value = int.from_bytes(raw, "big", signed=False)
    return value if value < 2**63 else value - 2**64


@contextmanager
def execution_lock(db: Session, scope: str, key: str):
    lock_id = _lock_id(scope, key)
    # Use a dedicated physical connection. The business Session commits several
    # times during reservation and may return its connection to the pool; a
    # session-level advisory lock must never be left attached to that pooled
    # connection.
    with db.get_bind().connect() as lock_connection:
        lock_connection.execute(text("select pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})
        try:
            yield
        finally:
            lock_connection.execute(text("select pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
