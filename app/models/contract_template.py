"""合约模板：一组可复用的合约策略（系统预置 + 用户自建），供上架产品作基准。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ContractTemplate(Base):
    """合约模板（policies 为 schemas.product.Policy 数组）。"""
    __tablename__ = "contract_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 策略数组（见 schemas.product.Policy）
    policies: Mapped[list | None] = mapped_column(JSON, nullable=True)

    scope: Mapped[str] = mapped_column(String(16), default="user")  # system | user
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)  # user 模板属主；system 模板为空

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
