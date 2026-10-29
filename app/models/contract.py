"""标准数字合约：当前文档 + 不可变版本记录。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DigitalContract(Base):
    """标准合约聚合根；document 是唯一业务事实来源。"""
    __tablename__ = "digital_contract"

    contract_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["DigitalContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan",
        order_by="DigitalContractVersion.version",
    )


class DigitalContractVersion(Base):
    """每次提案和生命周期推进产生的完整、不可变合约文档。"""
    __tablename__ = "digital_contract_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contract_id: Mapped[str] = mapped_column(
        String(47), ForeignKey("digital_contract.contract_id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(16))
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contract: Mapped["DigitalContract"] = relationship(back_populates="versions")
