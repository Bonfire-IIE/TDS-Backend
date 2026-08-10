"""数据产品：在一个已登记资源之上的可交易封装（携带基准合约 + 磋商模式 + 上架状态）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DataProduct(Base):
    """数据产品（1 产品 → 1 资源）。"""
    __tablename__ = "data_product"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 65 位产品码：上架时分配（gen_data_code('product', ...)）
    tds_code: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 底层资源（data_catalog.id）与冗余的执行落点信息
    resource_id: Mapped[str] = mapped_column(String(36))
    provider_connector_id: Mapped[str] = mapped_column(String(36))
    kuscia_domain_id: Mapped[str] = mapped_column(String(63))

    # accept(提案-接受/公益) | negotiate(提案-修订-共识)
    transaction_mode: Mapped[str] = mapped_column(String(16))
    # 基准合约策略数组（见 schemas.contract.Policy）
    baseline_policies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 产品声明支持的应用能力（app_image name 列表；为 job 选 app_image 铺路，可空）
    allowed_appimages: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="listed")  # listed/delisted
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # 软删除标记：仅打标记，记录留档存证；列表/详情排除已删
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
