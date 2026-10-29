"""Application signing keys bound to authenticated Keycloak subjects."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class UserSigningKey(Base):
    __tablename__ = "user_signing_key"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    key_id: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm: Mapped[str] = mapped_column(String(32), default="Ed25519")
    public_key_pem: Mapped[str] = mapped_column(String(2048))
    public_key_sha256: Mapped[str] = mapped_column(String(64))
    private_key_ref: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
