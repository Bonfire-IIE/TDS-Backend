"""数据产品请求/响应模型（含策略模型 Policy）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
import re

from pydantic import BaseModel, Field, field_validator

# 操作词表（10）：transform/access/read/reproduce/storage/download/process/jointDevelop/export/grantUse
ACTIONS = {
    "transform", "access", "read", "reproduce", "storage",
    "download", "process", "jointDevelop", "export", "grantUse",
}
OBLIGATIONS = {"ephemeral", "watermark", "no_download", "no_export"}


class TimeWindow(BaseModel):
    """时间窗口约束（绝对区间，ISO 字符串）。"""
    model_config = {"populate_by_name": True}

    from_: str | None = Field(None, alias="from")
    to: str | None = None


class Constraints(BaseModel):
    """策略约束（3）：time_window / count / exec_env。"""
    time_window: TimeWindow | None = None
    count: int | None = None
    # Execution environments are registered by the data-utilization engine.
    # Keep this as a bounded identifier rather than a platform-owned enum so
    # an engine such as Kuscia/PSI can use its published code (for example,
    # ``psi``) without requiring a center release.
    exec_env: str | None = Field(default=None, min_length=1, max_length=64)


class Policy(BaseModel):
    """单条策略：allow / prohibit + 操作集 + 约束。"""
    type: Literal["allow", "prohibit"]
    actions: list[str] = Field(default_factory=list)
    constraints: Constraints | None = None
    obligations: list[str] = Field(default_factory=list)

    @field_validator("actions")
    @classmethod
    def _valid_actions(cls, v: list[str]) -> list[str]:
        bad = [a for a in v if a not in ACTIONS]
        if bad:
            raise ValueError(f"非法操作 {bad}，仅允许 {sorted(ACTIONS)}")
        return v

    @field_validator("obligations")
    @classmethod
    def _valid_obligations(cls, v: list[str]) -> list[str]:
        bad = [item for item in v if item not in OBLIGATIONS]
        if bad:
            raise ValueError(f"非法义务 {bad}，仅允许 {sorted(OBLIGATIONS)}")
        return list(dict.fromkeys(v))


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str = Field(..., min_length=1, max_length=500)
    product_type: Literal["01", "02", "03", "04", "05", "06"]
    industry_code: str = Field(..., min_length=1, max_length=1)
    region_code: str | None = None
    time_range: str | None = None
    application_scenarios: str = Field(..., min_length=1)
    personal_information_level: Literal["0", "1", "2"]
    public_data: bool = False
    delivery_method: Literal["01", "02", "03", "04"]
    usage_limitations: str
    authorization_required: bool = False
    data_subject_type: Literal["01", "02", "03"]
    data_size: str | None = None
    update_frequency: str = Field(..., min_length=1, max_length=16)
    applicable_model_types: list[str] = Field(default_factory=list)
    ai_usage_scenarios: list[str] = Field(default_factory=list)
    provider_name: str
    provider_type: Literal["01", "02", "03"]
    provider_identity_id: str
    provider_description: str
    provider_entity_info: dict = Field(default_factory=dict)
    operator_name: str | None = None
    operator_telephone: str | None = None
    operator_id_card: str | None = None
    declarations: dict[str, str] = Field(..., description="中心附件对象引用：compliance、data_source、ai_training_license")
    resource_ids: list[str] = Field(..., min_length=1)
    processing_description: str = Field(..., min_length=1, max_length=4000, description="基于所选资源进行的实质加工与形成的产品价值")

    @field_validator("processing_description")
    @classmethod
    def validate_processing(cls, value: str) -> str:
        if not value.strip(): raise ValueError("请说明资源加工过程与产品价值")
        return value.strip()

    @field_validator("resource_ids")
    @classmethod
    def unique_resources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)): raise ValueError("数据资源不能重复选择")
        return value
    transaction_mode: Literal["accept", "negotiate"] = "accept"
    baseline_policies: list[Policy] = Field(default_factory=list)
    platform_name: str | None = None
    platform_id: str | None = None
    platform_location: str | None = None
    delivery_mode: Literal["01", "02", "03", "04", "05", "06", "07"] | None = None
    measure_method: str | None = None
    measure_unit: str | None = None
    price: float | None = Field(None, ge=0)
    delivery_info: str | None = None
    # 可选：以合约模板 policies 作为基准（未显式给 baseline_policies 时以模板为准）
    template_id: str | None = None

    @field_validator("industry_code")
    @classmethod
    def validate_industry(cls, value: str) -> str:
        value = value.upper()
        if not re.fullmatch(r"[A-T]", value):
            raise ValueError("行业分类必须使用 GB/T 4754 门类代码 A-T")
        return value

    @field_validator("declarations")
    @classmethod
    def validate_declarations(cls, value: dict) -> dict:
        missing = [key for key in ("compliance", "data_source", "ai_training_license") if not value.get(key)]
        if missing:
            raise ValueError(f"缺少必需的声明附件引用: {', '.join(missing)}")
        return value


class ProductPublish(BaseModel):
    platform_name: str = Field(..., min_length=1, max_length=128)
    platform_id: str = Field(..., min_length=1, max_length=80)
    platform_location: str = Field(..., min_length=1, max_length=128)
    delivery_mode: Literal["01", "02", "03", "04", "05", "06", "07"]
    measure_method: str = Field(..., min_length=1, max_length=16)
    measure_unit: str = Field(..., min_length=1, max_length=16)
    price: float = Field(..., ge=0, allow_inf_nan=False)
    delivery_info: str = Field(..., min_length=1)

    @field_validator("platform_name", "platform_id", "platform_location", "measure_method", "measure_unit", "delivery_info")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip(): raise ValueError("上架信息不能为空")
        return value.strip()


class ProductOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    description: str | None
    product_type: str
    industry_code: str
    region_code: str | None
    time_range: str | None
    application_scenarios: str
    personal_information_level: str
    public_data: bool
    delivery_method: str
    usage_limitations: str
    authorization_required: bool
    data_subject_type: str
    data_size: str | None
    update_frequency: str | None
    applicable_model_types: list | None
    ai_usage_scenarios: list | None
    provider_name: str
    provider_type: str
    provider_identity_id: str
    provider_description: str
    provider_entity_info: dict
    operator_name: str | None
    operator_telephone: str | None
    operator_id_card: str | None
    declarations: dict[str, str] | None
    platform_name: str | None
    platform_id: str | None
    platform_location: str | None
    delivery_mode: str | None
    measure_method: str | None
    measure_unit: str | None
    price: float | None
    delivery_info: str | None
    resource_ids: list[str] = Field(default_factory=list)
    resource_codes: list[str] = Field(default_factory=list)
    processing_description: str | None = None
    resource_id: str | None = None
    provider_connector_id: str | None = None
    transaction_mode: str
    baseline_policies: list | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    # 关联底层资源名称（从 data_catalog 取，便于前端详情展示；可能为空）
    resource_name: str | None = None

    model_config = {"from_attributes": True}
