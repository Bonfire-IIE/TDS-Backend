"""数据目录：数据资源条目 + 受控代码字典。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DataCatalog(Base):
    """中心侧数据资源目录投影；资源主记录由连接器维护。"""
    __tablename__ = "data_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tds_code: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="resource")
    # 数据类型：table(结构化) / image / text / file / other；仅 table 有列定义
    data_type: Mapped[str] = mapped_column(String(16), default="table")

    # 归属连接器；实际资源记录和访问配置位于连接器 SQLite。
    provider_connector_id: Mapped[str] = mapped_column(String(36))

    # 分类分级（受控代码，见 catalog_code_dict）
    industry_code: Mapped[str] = mapped_column(String(8), default="")
    theme_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resource_owner_name: Mapped[str] = mapped_column(String(128), default="")
    resource_owner_id: Mapped[str] = mapped_column(String(64), default="")
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    contact_information: Mapped[str] = mapped_column(String(128), default="")
    resource_abstract: Mapped[str] = mapped_column(Text, default="")
    resource_format: Mapped[str] = mapped_column(String(64), default="")
    resource_category: Mapped[str | None] = mapped_column(String(8), nullable=True)  # legacy alias
    source_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    delivery_form: Mapped[str | None] = mapped_column(String(8), nullable=True)
    update_freq: Mapped[str | None] = mapped_column(String(16), nullable=True)
    update_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_size: Mapped[str | None] = mapped_column(String(128), nullable=True)
    time_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_level: Mapped[str | None] = mapped_column(String(4), nullable=True)
    security_level: Mapped[str] = mapped_column(String(16), default="general_1")
    personal_information_level: Mapped[str] = mapped_column(String(2), default="0")
    resource_quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    high_quality_flag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_modalities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contains_synthetic_data: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ai_readiness: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_task_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    annotation_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_training_authorization: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    topic_category: Mapped[str | None] = mapped_column(String(16), nullable=True)

    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    columns: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{name,type,comment}]
    relative_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Connector-local source reference. The center never owns source credentials
    # or a separate data-source lifecycle.
    datasource_id: Mapped[str] = mapped_column(String(64))
    datasource_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    datasource_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    datasource_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[str] = mapped_column(String(24), default="pending_review")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # 软删除标记：仅打标记，记录留档存证；列表/详情排除已删
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class CatalogCodeDict(Base):
    """受控代码字典（7 张代码表落库，可扩展）。"""
    __tablename__ = "catalog_code_dict"
    __table_args__ = (UniqueConstraint("table_key", "code", name="uq_codedict_table_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    table_key: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(8))
    name_cn: Mapped[str] = mapped_column(String(64))
