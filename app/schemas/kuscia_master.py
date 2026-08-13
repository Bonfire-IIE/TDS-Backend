"""Request and response schemas for imported Kuscia Master nodes."""
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from pydantic import BaseModel, Field, IPvAnyAddress


class KusciaMasterImport(BaseModel):
    name: str = Field("Kuscia Master", min_length=1, max_length=128)
    domain_id: str = Field(..., pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", max_length=63)
    deployment_ip: IPvAnyAddress
    auth_port: int = Field(..., ge=1, le=65535)
    api_port: int = Field(..., ge=1, le=65535)
    grpc_port: int = Field(..., ge=1, le=65535)
    app_port: int = Field(..., ge=1, le=65535)
    metrics_port: int = Field(..., ge=1, le=65535)
    scheme: str = Field("https", pattern="^(http|https)$")
    deploy_endpoint: str | None = None


class KusciaMasterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    domain_id: str | None = Field(None, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", max_length=63)
    deployment_ip: IPvAnyAddress | None = None
    auth_port: int | None = Field(None, ge=1, le=65535)
    api_port: int | None = Field(None, ge=1, le=65535)
    grpc_port: int | None = Field(None, ge=1, le=65535)
    app_port: int | None = Field(None, ge=1, le=65535)
    metrics_port: int | None = Field(None, ge=1, le=65535)
    scheme: str | None = Field(None, pattern="^(http|https)$")
    deploy_endpoint: str | None = None
    enabled: bool | None = None


class KusciaMasterDeployGuide(BaseModel):
    domain_id: str = Field(
        "bonfire-master",
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
        min_length=1,
        max_length=63,
    )
    deployment_ip: IPvAnyAddress
    auth_port: int = Field(13081, ge=1, le=65535)
    api_port: int = Field(13082, ge=1, le=65535)
    grpc_port: int = Field(13083, ge=1, le=65535)
    app_port: int = Field(13080, ge=1, le=65535)
    metrics_port: int = Field(13084, ge=1, le=65535)
    kuscia_image: str | None = Field(None, max_length=512)


class KusciaMasterOut(BaseModel):
    id: str
    name: str
    domain_id: str
    deployment_ip: str
    auth_port: int
    api_port: int
    grpc_port: int
    app_port: int
    metrics_port: int
    scheme: str
    deploy_endpoint: str | None
    credential_ref: str | None
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def normalized_ip(value: IPv4Address | IPv6Address) -> str:
    return str(value)
