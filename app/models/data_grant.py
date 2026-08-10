"""DomainDataGrant 追踪：记录为每次运行建立的跨域数据授权，以便运行终态时回收。"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

def _id(): return str(uuid.uuid4())

class DataGrant(Base):
    __tablename__ = "data_grant"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    project_run_id: Mapped[str] = mapped_column(String(36), index=True)
    domain_id: Mapped[str] = mapped_column(String(63))          # 授权发起域(数据属主域)
    domaindata_id: Mapped[str] = mapped_column(String(63))
    grant_domain: Mapped[str] = mapped_column(String(63))        # 被授权域
    kuscia_grant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
