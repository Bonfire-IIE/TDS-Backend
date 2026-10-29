"""标准数字合约 API 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.product import Policy


class ContractRequest(BaseModel):
    """从数据产品发起合约；服务端补齐标的、节点和签署主体。"""
    consumer_connector_id: str
    purpose: str | None = None
    confirm: str | None = None
    policies: list[Policy] | None = None
    execution_env: str = "0601"
    # Optional contract-level application restriction. A product contract may
    # authorize a class of use without selecting the concrete project workflow.
    application_code: str | None = Field(default=None, max_length=128)
    policy_expansion: dict[str, Any] | None = None
    contract_expansion: dict[str, Any] | None = None


class ProposeRequest(BaseModel):
    """提交完整标准策略集；不接受旧平台 Policy 作为合约存储模型。"""
    contract_policies: list[dict[str, Any]] = Field(min_length=1)
    contract_expansion: dict[str, Any] | None = None


class ContractVersionOut(BaseModel):
    version: int
    operation: str
    document_hash: str
    previous_hash: str | None
    created_by: str | None
    created_at: datetime
    document: dict[str, Any]

    model_config = {"from_attributes": True}


class ContractOut(BaseModel):
    contract_id: str
    document: dict[str, Any]
    document_hash: str
    current_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    versions: list[ContractVersionOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}
