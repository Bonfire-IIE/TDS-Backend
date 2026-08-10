"""数据产品请求/响应模型（含策略模型 Policy）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 操作词表（10）：transform/access/read/reproduce/storage/download/process/jointDevelop/export/grantUse
ACTIONS = {
    "transform", "access", "read", "reproduce", "storage",
    "download", "process", "jointDevelop", "export", "grantUse",
}


class TimeWindow(BaseModel):
    """时间窗口约束（绝对区间，ISO 字符串）。"""
    model_config = {"populate_by_name": True}

    from_: str | None = Field(None, alias="from")
    to: str | None = None


class Constraints(BaseModel):
    """策略约束（3）：time_window / count / exec_env。"""
    time_window: TimeWindow | None = None
    count: int | None = None
    exec_env: Literal["mpc", "sandbox", "tee", "plain"] | None = None


class Policy(BaseModel):
    """单条策略：allow / prohibit + 操作集 + 约束。"""
    type: Literal["allow", "prohibit"]
    actions: list[str] = Field(default_factory=list)
    constraints: Constraints | None = None

    @field_validator("actions")
    @classmethod
    def _valid_actions(cls, v: list[str]) -> list[str]:
        bad = [a for a in v if a not in ACTIONS]
        if bad:
            raise ValueError(f"非法操作 {bad}，仅允许 {sorted(ACTIONS)}")
        return v


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    resource_id: str
    transaction_mode: Literal["accept", "negotiate"]
    baseline_policies: list[Policy] = Field(default_factory=list)
    # 可选：以合约模板 policies 作为基准（未显式给 baseline_policies 时以模板为准）
    template_id: str | None = None
    # 可选：产品支持的应用能力（app_image name 列表），为 job 选 app_image 铺路
    allowed_appimages: list[str] | None = None


class ProductOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    description: str | None
    resource_id: str
    provider_connector_id: str
    kuscia_domain_id: str
    transaction_mode: str
    baseline_policies: list | None
    allowed_appimages: list | None = None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    # 关联底层资源名称（从 data_catalog 取，便于前端详情展示；可能为空）
    resource_name: str | None = None

    model_config = {"from_attributes": True}
