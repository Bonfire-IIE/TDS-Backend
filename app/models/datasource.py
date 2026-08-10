"""数据源：平台侧管理的 Kuscia DomainDataSource（localfs / oss）。

DomainDataSource 的 info 含加密字段，须由 Lite 节点自身签发，master 无权操作，
故创建时经该连接器(domain)的 Lite KusciaAPI 下发。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DataSource(Base):
    """一个 Kuscia DomainDataSource 在平台侧的管理对象。"""
    __tablename__ = "data_source"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16))  # localfs | oss

    # 归属连接器（= 数据所在 Kuscia domain）
    connector_id: Mapped[str] = mapped_column(String(36))
    kuscia_domain_id: Mapped[str] = mapped_column(String(63))
    kuscia_datasource_id: Mapped[str] = mapped_column(String(64))

    # localfs: 节点内路径；oss: s3 url / bucket 描述
    uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 非密连接信息（oss 存 endpoint/bucket/prefix 等；
    # 注意：MVP 保留字段，AK/SK 绝不落库明文，生产应加密或走 K8s Secret）
    info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
