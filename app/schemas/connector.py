"""连接器请求/响应模型。"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Kuscia domain_id 需符合 RFC1123（小写字母数字与连字符）
_DOMAIN_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_RESERVED = {"default", "kube-system", "kube-public", "kube-node-lease", "master", "cross-domain"}


class ConnectorApply(BaseModel):
    name: str = Field(..., max_length=128)
    kuscia_domain_id: str = Field(..., max_length=63)
    org_name: str | None = Field(None, max_length=255)
    lite_api_endpoint: str = Field(..., max_length=255, description="Lite KusciaAPI 可达地址")
    lite_api_port: int = Field(..., ge=1, le=65535)
    auth_port: int = Field(1080, ge=1, le=65535)
    grpc_port: int = Field(8083, ge=1, le=65535)
    app_port: int = Field(80, ge=1, le=65535)
    data_port: int = Field(9091, ge=1, le=65535)

    @field_validator("kuscia_domain_id")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        if not _DOMAIN_RE.match(v):
            raise ValueError("domain_id 需为 RFC1123 格式（小写字母数字与连字符）")
        if v in _RESERVED:
            raise ValueError(f"domain_id '{v}' 为 Kuscia 保留字")
        return v


class ConnectorImport(BaseModel):
    """导入已有 Kuscia Domain（如 alice/bob）为连接器。"""
    kuscia_domain_id: str
    name: str | None = None
    org_name: str | None = None
    lite_api_endpoint: str | None = None
    lite_api_port: int | None = Field(None, ge=1, le=65535)
    auth_port: int | None = Field(None, ge=1, le=65535)
    grpc_port: int | None = Field(None, ge=1, le=65535)
    app_port: int | None = Field(None, ge=1, le=65535)
    data_port: int | None = Field(None, ge=1, le=65535)


class ConnectorUpdate(BaseModel):
    name: str = Field(..., max_length=128)
    org_name: str | None = Field(None, max_length=255)
    lite_api_endpoint: str = Field(..., max_length=255)
    lite_api_port: int = Field(..., ge=1, le=65535)
    auth_port: int = Field(..., ge=1, le=65535)
    grpc_port: int = Field(..., ge=1, le=65535)
    app_port: int = Field(..., ge=1, le=65535)
    data_port: int = Field(..., ge=1, le=65535)


class NodeInfoReport(BaseModel):
    """连接器门户部署完 Lite 后回传的节点物理信息（部分字段，仅更新提供的项）。

    关键：lite_api_endpoint 应为**物理主机地址**、auth_port 为**已发布网关端口**，
    据此中心用于跨机 CDR 的正确 endpoint（见 CDR 物理地址修复）。
    """
    endpoint: str | None = Field(None, max_length=255)
    lite_api_endpoint: str | None = Field(None, max_length=255)
    lite_api_port: int | None = Field(None, ge=1, le=65535)
    auth_port: int | None = Field(None, ge=1, le=65535)
    grpc_port: int | None = Field(None, ge=1, le=65535)
    app_port: int | None = Field(None, ge=1, le=65535)
    data_port: int | None = Field(None, ge=1, le=65535)


class ConnectorOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    org_name: str | None
    kuscia_domain_id: str
    status: str  # applying/approved/rejected/online/offline（后两者为派生展示值）
    endpoint: str | None
    lite_api_endpoint: str | None
    lite_api_port: int | None
    auth_port: int | None
    grpc_port: int | None
    app_port: int | None
    data_port: int | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeployInfo(BaseModel):
    """审批后返回的部署信息（令牌实时取自 Kuscia，不落库）。"""
    kuscia_domain_id: str
    deploy_token: str | None
    master_endpoint: str
    kuscia_image: str
    commands: str  # 供“命令展示器”渲染的多行 bash
