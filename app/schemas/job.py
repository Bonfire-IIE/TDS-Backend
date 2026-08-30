"""隐私计算作业请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    """发起一次作业：基于合约选应用 + 指定两方输入。"""
    contract_id: str
    app_image: str
    # 供/用两方输入 DomainData id（各留本地，不出域）
    input_provider_domaindata_id: str
    input_consumer_domaindata_id: str
    # 求交列名（两方主键列），默认 ["id"]
    join_keys: list[str] = Field(default_factory=lambda: ["id"])
    # 可选作业名（缺省用合约名派生）
    name: str | None = None
    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class JobOut(BaseModel):
    id: str
    job_code: str
    name: str
    contract_id: str
    usage_record_id: str | None
    usage_record_ids: list | None = None
    product_id: str | None
    app_image: str
    initiator_connector_id: str
    initiator_domain: str
    provider_connector_id: str
    provider_domain: str
    consumer_connector_id: str
    consumer_domain: str
    input_provider_domaindata_id: str
    input_consumer_domaindata_id: str
    kuscia_job_id: str | None
    status: str
    result_domaindata_id: str | None
    result_uri: str | None
    error: str | None
    failure_info: dict | None
    obligations: dict | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    idempotency_key: str | None = None

    model_config = {"from_attributes": True}
