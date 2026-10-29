"""Platform-level capability and application mappings.

These models intentionally contain no Kuscia identifiers. A downstream
execution system adapter may keep its own implementation references outside
the platform domain model.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _id() -> str:
    return str(uuid.uuid4())


class ConnectorCapability(Base):
    __tablename__ = "connector_capability"
    __table_args__ = (UniqueConstraint("connector_id", "capability_code", name="uq_connector_capability"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    connector_id: Mapped[str] = mapped_column(String(36), ForeignKey("connector.id", ondelete="CASCADE"), index=True)
    capability_code: Mapped[str] = mapped_column(String(64), index=True)
    capability_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    adapter_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    implementation_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="declared")
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DataResourceBinding(Base):
    """Binding between a platform resource and a connector-local resource."""
    __tablename__ = "data_resource_binding"
    __table_args__ = (UniqueConstraint("platform_resource_id", "connector_id", name="uq_resource_connector_binding"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    platform_resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_catalog.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[str] = mapped_column(String(36), ForeignKey("connector.id", ondelete="CASCADE"), index=True)
    connector_resource_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="platform")
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), default="pending")
    metadata_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrivacyApplication(Base):
    __tablename__ = "privacy_application"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_env_code: Mapped[str] = mapped_column(String(64), index=True)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extension_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="published")
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrivacyApplicationBinding(Base):
    __tablename__ = "privacy_application_binding"
    __table_args__ = (UniqueConstraint("application_code", "system_type", "system_application_ref", name="uq_privacy_app_binding"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    application_code: Mapped[str] = mapped_column(String(128), ForeignKey("privacy_application.code", ondelete="CASCADE"), index=True)
    system_type: Mapped[str] = mapped_column(String(64))
    system_application_ref: Mapped[str] = mapped_column(String(255))
    system_application_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability_requirements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="published")
    implementation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
