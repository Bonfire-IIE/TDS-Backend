"""Contract-bound privacy-computing business objects."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _id() -> str:
    return str(uuid.uuid4())


class PrivacyComputeProject(Base):
    __tablename__ = "privacy_compute_project"
    __table_args__ = (UniqueConstraint("contract_id", name="uq_privacy_compute_project_contract"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_id: Mapped[str] = mapped_column(String(47), ForeignKey("digital_contract.contract_id"), index=True)
    contract_version: Mapped[int] = mapped_column(nullable=False)
    contract_document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    application_code: Mapped[str] = mapped_column(String(128), index=True)
    configuration: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrivacyComputeRun(Base):
    __tablename__ = "privacy_compute_run"
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_privacy_compute_run_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("privacy_compute_project.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    system_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_run_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
