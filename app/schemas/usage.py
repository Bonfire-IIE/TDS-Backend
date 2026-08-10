"""使用控制查询响应。"""
from datetime import datetime

from pydantic import BaseModel, Field


class UsageRecordOut(BaseModel):
    id: str
    request_id: str
    contract_id: str
    connector_id: str
    username: str
    action: str
    decision: str
    lifecycle: str
    job_id: str | None
    reason: str | None
    matched_policy_ids: list | None
    context: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UsagePreflightOut(BaseModel):
    allowed: bool
    decision: str
    reason: str
    matched_policy_ids: list
    used_count: int
    reserved_count: int
    max_count: int | None = None
    checks: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}
