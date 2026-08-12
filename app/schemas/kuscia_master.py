"""Request and response schemas for imported Kuscia Master nodes."""
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from pydantic import BaseModel, Field, IPvAnyAddress


class KusciaMasterImport(BaseModel):
    name: str = Field("Kuscia Master", min_length=1, max_length=128)
    deployment_ip: IPvAnyAddress
    api_port: int = Field(..., ge=1, le=65535)
    scheme: str = Field("https", pattern="^(http|https)$")
    deploy_endpoint: str | None = None


class KusciaMasterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    deployment_ip: IPvAnyAddress | None = None
    api_port: int | None = Field(None, ge=1, le=65535)
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
    api_port: int = Field(18081, ge=1, le=65535)
    gateway_port: int = Field(18080, ge=1, le=65535)
    kuscia_image: str | None = Field(None, max_length=512)


class KusciaMasterOut(BaseModel):
    id: str
    name: str
    deployment_ip: str
    api_port: int
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
