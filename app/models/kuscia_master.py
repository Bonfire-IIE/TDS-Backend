"""Imported Kuscia Master nodes managed by the center platform."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class KusciaMaster(Base):
    __tablename__ = "kuscia_master"
    __table_args__ = (
        UniqueConstraint("deployment_ip", "api_port", name="uq_kuscia_master_endpoint"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128))
    deployment_ip: Mapped[str] = mapped_column(String(45))
    api_port: Mapped[int] = mapped_column(Integer)
    scheme: Mapped[str] = mapped_column(String(8), default="https")
    deploy_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="unconfigured")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
