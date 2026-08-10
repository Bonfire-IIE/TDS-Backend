"""使用控制决策记录与并发安全计数器。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UsageCounter(Base):
    __tablename__ = "usage_counter"
    __table_args__ = (UniqueConstraint("contract_id", "action"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id: Mapped[str] = mapped_column(String(47), index=True)
    action: Mapped[str] = mapped_column(String(32))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    reserved_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageRecord(Base):
    __tablename__ = "usage_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    contract_id: Mapped[str] = mapped_column(String(47), index=True)
    connector_id: Mapped[str] = mapped_column(String(36))
    username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(32))
    lifecycle: Mapped[str] = mapped_column(String(16), default="decided")
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_policy_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
