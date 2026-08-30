from datetime import datetime

from pydantic import BaseModel, Field


class ProjectTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    workflow: dict


class ProjectTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    workflow: dict | None = None


class ProjectTemplateOut(BaseModel):
    id: str
    name: str
    description: str | None
    workflow: dict
    owner: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
