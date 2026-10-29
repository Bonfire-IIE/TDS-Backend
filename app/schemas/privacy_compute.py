from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PrivacyProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    contract_id: str
    application_code: str = Field(min_length=1, max_length=128)
    configuration: dict[str, Any] | None = None


class PrivacyProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    contract_id: str
    contract_version: int
    contract_document_hash: str
    application_code: str
    configuration: dict[str, Any] | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PrivacyRunOut(BaseModel):
    id: str
    project_id: str
    status: str
    system_type: str | None
    external_run_ref: str | None
    result: dict[str, Any] | None
    evidence: dict[str, Any] | None
    error: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PrivacyRunCreate(BaseModel):
    input_provider_ref: str
    input_consumer_ref: str
    join_keys: list[str] = Field(min_length=1)
    implementation_ref: str | None = None
    idempotency_key: str | None = Field(None, max_length=128)
