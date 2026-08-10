"""连接器 = 一个 Kuscia Lite 节点(Domain) 在平台侧的管理对象。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Connector(Base):
    __tablename__ = "connector"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # TDS 32 位标识码：审批时分配，一经分配不可变更（应用层保证）
    tds_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    org_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 对应 Kuscia Domain（namespace），唯一
    kuscia_domain_id: Mapped[str] = mapped_column(String(63), unique=True)
    # 存储态：applying / approved / rejected（online/offline 由 Kuscia 实时派生，不落库）
    status: Mapped[str] = mapped_column(String(16), default="applying")
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lite_api_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lite_api_port: Mapped[int | None] = mapped_column(nullable=True)
    auth_port: Mapped[int | None] = mapped_column(nullable=True)
    grpc_port: Mapped[int | None] = mapped_column(nullable=True)
    app_port: Mapped[int | None] = mapped_column(nullable=True)
    data_port: Mapped[int | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # 软删除标记：非空表示已删除（列表排除、查重排除、按 404 处理）
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
