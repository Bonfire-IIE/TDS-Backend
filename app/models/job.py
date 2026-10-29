"""隐私计算作业(Job)：基于一份已备案数字合约，在供/用两个连接器间执行一次隐私计算。

MVP = 两方 PSI 求交；结果落各方本地（数据不出域）。作业是"合约→授权→应用→
执行→数据不出域"闭环的最后一环：合约(filed) + 应用(AppImage) + 双方输入 DomainData
→ 组装 task_input_config → 提交 KusciaJob → 轮询状态 → 结果 DomainData。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    """一次隐私计算作业。"""
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 作业码（展示/追溯用）
    job_code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    # 依据的数字合约（必须为 filed）
    contract_id: Mapped[str] = mapped_column(String(47))
    usage_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 选用的应用能力（= Kuscia AppImage name）
    app_image: Mapped[str] = mapped_column(String(128))

    # 发起方 / 供数方 / 用数方（连接器 + Kuscia domain 冗余）
    initiator_connector_id: Mapped[str] = mapped_column(String(36))
    initiator_domain: Mapped[str] = mapped_column(String(63))
    provider_connector_id: Mapped[str] = mapped_column(String(36))
    provider_domain: Mapped[str] = mapped_column(String(63))
    consumer_connector_id: Mapped[str] = mapped_column(String(36))
    consumer_domain: Mapped[str] = mapped_column(String(63))

    # 两方输入 DomainData（各留本地，求交列由 join_keys 指定）
    input_provider_domaindata_id: Mapped[str] = mapped_column(String(63))
    input_consumer_domaindata_id: Mapped[str] = mapped_column(String(63))

    # 提交给 Kuscia 的作业 id（= cross-domain 下 KusciaJob 名）
    kuscia_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # pending / running / succeeded / failed
    status: Mapped[str] = mapped_column(String(16), default="pending")

    # 结果（succeeded 时回填）
    result_domaindata_id: Mapped[str | None] = mapped_column(String(63), nullable=True)
    result_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured control-plane failure summary; never contains raw connector logs.
    failure_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
