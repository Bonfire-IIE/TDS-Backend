"""连接器软件部署和机器身份注册 API。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConnectorApply(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    org_name: str | None = Field(None, max_length=255)
    csr_pem: str = Field(..., min_length=64, max_length=16384)


class ConnectorImport(ConnectorApply):
    """由运营方登记已经生成 CSR 的连接器。"""


class ConnectorUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    org_name: str | None = Field(None, max_length=255)


class ConnectorActivate(BaseModel):
    certificate_fingerprint: str = Field(..., min_length=64, max_length=64)


class ConnectorOut(BaseModel):
    id: str
    tds_code: str | None
    name: str
    org_name: str | None
    status: str
    csr_fingerprint: str
    public_key_fingerprint: str
    certificate_serial: str | None
    certificate_not_before: datetime | None
    certificate_not_after: datetime | None
    activated_at: datetime | None
    last_seen_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorCertificateOut(BaseModel):
    connector_id: str
    certificate_pem: str
    ca_certificate_pem: str
    fingerprint: str
    not_after: datetime


class DeploymentInstructionOut(BaseModel):
    system: Literal["linux"]
    deployment_platform: Literal["docker-compose", "kubernetes"]
    architecture: Literal["amd64", "arm64"]
    version: str
    commands: str
    notes: list[str]
