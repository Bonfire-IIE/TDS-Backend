"""数字合约请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.product import Policy


class ContractRequest(BaseModel):
    """用数方发起合约请求。"""
    consumer_connector_id: str
    purpose: str | None = None
    confirm: str | None = None  # accept 模式：需等于产品 name（打字确认）
    policies: list[Policy] | None = None  # negotiate 模式：可带修改后的策略
    allowed_appimages: list[str] | None = None


class ProposeRequest(BaseModel):
    """提交一轮修订策略。"""
    policies: list[Policy] = Field(default_factory=list)
    allowed_appimages: list[str] | None = None


class PartyOut(BaseModel):
    party_role: str  # provider | consumer
    connector_id: str
    entity: str | None
    signature_hash: str | None
    signed_at: datetime | None

    model_config = {"from_attributes": True}


class HistoryOut(BaseModel):
    round: int
    op: str
    operator: str | None
    created_at: datetime
    snapshot: dict | None = None

    model_config = {"from_attributes": True}


class ContractOut(BaseModel):
    contract_id: str
    name: str
    abstract: str | None
    purpose: str | None
    product_id: str
    provider_connector_id: str
    consumer_connector_id: str
    mode: str
    status: str
    policies: list | None
    allowed_appimages: list | None = None
    contract_hash: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    parties: list[PartyOut] = Field(default_factory=list)
    history: list[HistoryOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}
