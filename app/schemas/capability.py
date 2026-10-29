from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CapabilityCreate(BaseModel):
    capability_code: str = Field(min_length=1, max_length=64)
    capability_version: str | None = Field(None, max_length=32)
    adapter_type: str | None = Field(None, max_length=64)
    implementation_ref: str | None = Field(None, max_length=255)
    evidence: dict[str, Any] | None = None


class PrivacyComputeProvision(BaseModel):
    implementation_ref: str | None = Field(None, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class CapabilityOut(CapabilityCreate):
    id: str
    connector_id: str
    status: str
    verified_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationOut(BaseModel):
    code: str
    name: str
    description: str | None
    execution_env_code: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    extension_schema: dict[str, Any] | None
    status: str
    version: str
    execution_bindings: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}

class ApplicationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    execution_env_code: str = Field(min_length=1, max_length=64)
    version: str = Field(default="1.0.0", max_length=32)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    extension_schema: dict[str, Any] | None = None
    implementation_ref: str = Field(min_length=1, max_length=255)
    implementation_version: str | None = None
    capability_requirements: list[str | dict[str, Any]] = Field(default_factory=list)
    adapter_version: str | None = None
    implementation_metadata: dict[str, Any] = Field(default_factory=dict)
