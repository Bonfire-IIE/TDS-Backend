"""数据产品标准登记、资源关联和上架信息。"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

def _uuid() -> str: return str(uuid.uuid4())

class DataProduct(Base):
    __tablename__ = "data_product"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tds_code: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_type: Mapped[str] = mapped_column(String(2), default="01")
    industry_code: Mapped[str] = mapped_column(String(8), default="")
    region_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    time_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    application_scenarios: Mapped[str] = mapped_column(Text, default="")
    personal_information_level: Mapped[str] = mapped_column(String(2), default="0")
    public_data: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_method: Mapped[str] = mapped_column(String(2), default="04")
    usage_limitations: Mapped[str] = mapped_column(Text, default="")
    authorization_required: Mapped[bool] = mapped_column(Boolean, default=False)
    data_subject_type: Mapped[str] = mapped_column(String(2), default="02")
    data_size: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_frequency: Mapped[str] = mapped_column(String(16), default="其他")
    applicable_model_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_usage_scenarios: Mapped[list | None] = mapped_column(JSON, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(128), default="")
    provider_type: Mapped[str] = mapped_column(String(2), default="02")
    provider_identity_id: Mapped[str] = mapped_column(String(64), default="")
    provider_description: Mapped[str] = mapped_column(Text, default="")
    provider_entity_info: Mapped[dict] = mapped_column(JSON, default=dict)
    operator_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operator_telephone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operator_id_card: Mapped[str | None] = mapped_column(String(32), nullable=True)
    declarations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    platform_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    platform_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    platform_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(2), nullable=True)
    measure_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    measure_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    price: Mapped[float | None] = mapped_column(nullable=True)
    delivery_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider_connector_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    transaction_mode: Mapped[str] = mapped_column(String(16), default="accept")
    baseline_policies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="registered")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

class DataProductResource(Base):
    __tablename__ = "data_product_resource"
    __table_args__ = (UniqueConstraint("product_id", "resource_id", name="uq_product_resource"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_product.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_catalog.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="input")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
