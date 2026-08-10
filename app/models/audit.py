"""本地审计链、Rekor outbox 与锚点。"""
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (UniqueConstraint("stream_id", "sequence"),)

class AuditOutbox(Base):
    __tablename__ = "audit_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)

class AuditAnchor(Base):
    __tablename__ = "audit_anchor"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="rekor")
    rekor_uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    integrated_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    inclusion_proof: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
