"""Request and response schemas for imported Kuscia Master nodes."""
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from pydantic import BaseModel, Field, IPvAnyAddress


class KusciaMasterImport(BaseModel):
    name: str = Field("Kuscia Master", min_length=1, max_length=128)
    deployment_ip: IPvAnyAddress
    api_port: int = Field(..., ge=1, le=65535)


class KusciaMasterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    deployment_ip: IPvAnyAddress | None = None
    api_port: int | None = Field(None, ge=1, le=65535)
    enabled: bool | None = None


class KusciaMasterOut(BaseModel):
    id: str
    name: str
    deployment_ip: str
    api_port: int
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def normalized_ip(value: IPv4Address | IPv6Address) -> str:
    return str(value)
