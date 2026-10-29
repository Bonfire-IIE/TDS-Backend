"""连接器及其可选下游数据利用系统接入信息。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
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
    # 存储态：applying / approved / active / rejected / revoked
    status: Mapped[str] = mapped_column(String(16), default="applying")
    csr_pem: Mapped[str] = mapped_column(Text)
    csr_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    public_key_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    certificate_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_serial: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    certificate_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    certificate_not_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # 软删除标记：非空表示已删除（列表排除、查重排除、按 404 处理）
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
