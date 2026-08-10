"""合约模板请求/响应模型（策略复用 schemas.product.Policy）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.product import Policy


class TemplateCreate(BaseModel):
    """新建合约模板。scope 由服务层裁决（普通用户强制 user，operator 可建 system）。"""
    name: str = Field(..., max_length=255)
    description: str | None = None
    policies: list[Policy] = Field(default_factory=list)
    scope: Literal["system", "user"] | None = None


class TemplateUpdate(BaseModel):
    """编辑合约模板（部分字段）。"""
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    policies: list[Policy] | None = None


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str | None
    policies: list | None
    scope: str
    owner: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
