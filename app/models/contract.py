"""数字合约：合约信息 + 一组合约策略；多方签署 + 协商历史哈希链。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DigitalContract(Base):
    """一份数字合约（在产品与用数方连接器之间成立）。"""
    __tablename__ = "digital_contract"

    # 47 位合约码
    contract_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)

    product_id: Mapped[str] = mapped_column(String(36))
    provider_connector_id: Mapped[str] = mapped_column(String(36))
    consumer_connector_id: Mapped[str] = mapped_column(String(36))

    mode: Mapped[str] = mapped_column(String(16))  # accept | negotiate（继承自产品）
    # initiated/negotiating/signed/filed/executing/terminated/rejected
    status: Mapped[str] = mapped_column(String(16), default="initiated")

    policies: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 当前工作/已签策略集
    allowed_appimages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contract_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 备案存证码

    created_by: Mapped[str] = mapped_column(String(64))  # 用数方
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parties: Mapped[list["ContractParty"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan",
        order_by="ContractParty.party_role",
    )
    history: Mapped[list["NegotiationHistory"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan",
        order_by="NegotiationHistory.round",
    )


class ContractParty(Base):
    """合约参与方（provider/consumer）。"""
    __tablename__ = "contract_party"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(
        String(47), ForeignKey("digital_contract.contract_id", ondelete="CASCADE")
    )
    party_role: Mapped[str] = mapped_column(String(16))  # provider | consumer
    connector_id: Mapped[str] = mapped_column(String(36))
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)  # username
    signature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contract: Mapped["DigitalContract"] = relationship(back_populates="parties")


class NegotiationHistory(Base):
    """协商历史（防篡改哈希链）。"""
    __tablename__ = "negotiation_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(
        String(47), ForeignKey("digital_contract.contract_id", ondelete="CASCADE")
    )
    round: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = mapped_column(String(16))  # propose | revise | accept | reject
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 合约信息 + policies
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curr_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped["DigitalContract"] = relationship(back_populates="history")
