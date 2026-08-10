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
    """数据资源目录条目（kind=resource；product 后续）。"""
    __tablename__ = "data_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tds_code: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="resource")
    # 数据类型：table(结构化) / image / text / file / other；仅 table 有列定义
    data_type: Mapped[str] = mapped_column(String(16), default="table")

    # 归属连接器（= 数据所在 Kuscia domain）
    provider_connector_id: Mapped[str] = mapped_column(String(36))
    kuscia_domain_id: Mapped[str] = mapped_column(String(63))
    kuscia_domaindata_id: Mapped[str | None] = mapped_column(String(63), nullable=True)

    # 分类分级（受控代码，见 catalog_code_dict）
    resource_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    delivery_form: Mapped[str | None] = mapped_column(String(8), nullable=True)
    update_freq: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quality_level: Mapped[str | None] = mapped_column(String(4), nullable=True)
    security_level: Mapped[str] = mapped_column(String(4))  # 必填：安全分级
    service_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    topic_category: Mapped[str | None] = mapped_column(String(16), nullable=True)

    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    columns: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{name,type,comment}]
    relative_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    datasource_id: Mapped[str] = mapped_column(String(64), default="default-data-source")

    status: Mapped[str] = mapped_column(String(16), default="registered")  # registered/delisted
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
