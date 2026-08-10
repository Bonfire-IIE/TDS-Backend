"""AppImage（应用能力）请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AppImageCreate(BaseModel):
    # 可指定 Kuscia AppImage 名，便于复用已有 YAML/Job；不填时平台生成。
    name: str | None = Field(None, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    display_name: str = Field(..., max_length=255)
    description: str | None = None
    # 能力类别：mpc(安全多方计算) / stats / train / custom / general …
    capability: str = Field(..., max_length=32)
    # 操作属性(合约操作词表子集，如 read/process)；使用控制能力(ephemeral/watermark/…)
    operations: list[str] = Field(default_factory=list)
    uc_capabilities: list[str] = Field(default_factory=list)
    registry_source: Literal["platform", "third_party"] = "third_party"
    registry: str | None = Field(None, max_length=255)
    image_name: str = Field(..., max_length=512)
    image_tag: str = Field(..., max_length=128)
    # Kuscia AppImage 部署模板（扁平结构，见 KusciaClient.create_appimage）
    deploy_templates: list = Field(default_factory=list)
    config_templates: dict | None = None
    # 非 SecretFlow 应用的 KusciaJob task 模板（角色、输入配置等）。
    job_template: dict | None = None
    io_schema: dict | None = None
    party_schema: dict | None = None
    parameter_schema: dict | None = None
    ui_schema: dict | None = None
    task_input_template: dict | list | None = None


class AppImageParseRequest(BaseModel):
    content: str
    kind: Literal["appimage", "deploy_templates", "config_templates"]


class AppImageOut(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None
    capability: str
    operations: list | None
    uc_capabilities: list | None
    image_name: str
    image_tag: str
    registry_source: str
    registry: str | None
    deploy_templates: list | None
    config_templates: dict | None
    job_template: dict | None
    io_schema: dict | None
    party_schema: dict | None
    parameter_schema: dict | None
    ui_schema: dict | None
    task_input_template: dict | list | None
    status: str
    scope: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
