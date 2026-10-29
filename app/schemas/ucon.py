from pydantic import BaseModel, Field
class UconCheckRequest(BaseModel):
    stage: str
    checks: list[dict] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    project_id: str | None = None
    job_id: str | None = None
class UconCheckOut(BaseModel):
    id: str; contract_id: str; project_id: str | None; job_id: str | None; stage: str; decision: str; checks: list; evidence: dict; error: str | None; created_by: str | None
    model_config = {"from_attributes": True}
