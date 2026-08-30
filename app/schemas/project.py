from datetime import datetime
from pydantic import BaseModel, Field

class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = None
    contract_id: str

class WorkflowSubmit(BaseModel):
    workflow: dict

class RunCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

class ApprovalRequest(BaseModel):
    # 可空：省略时由后端按当前用户自动推导其所属的参与方连接器
    connector_id: str | None = None
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = None

class ProjectOut(BaseModel):
    id: str; name: str; description: str | None; contract_id: str
    initiator_connector_id: str; status: str; current_version: int | None
    created_by: str; created_at: datetime; updated_at: datetime
    model_config={"from_attributes":True}

class DomainOut(BaseModel):
    connector_id: str
    domain_id: str

class AvailableDomainDataOut(BaseModel):
    resource_id: str
    domaindata_id: str
    domain_id: str
    connector_id: str
    name: str
    data_type: str
    datasource_type: str | None = None
    format: str | None = None
    columns: list | None = None
    relative_uri: str | None = None

class VersionOut(BaseModel):
    id: str; version: int; workflow: dict; workflow_hash: str; status: str
    created_by: str; created_at: datetime
    model_config={"from_attributes":True}

class ApprovalOut(BaseModel):
    connector_id: str; decision: str; comment: str | None; decided_by: str; decided_at: datetime
    model_config={"from_attributes":True}

class RunOut(BaseModel):
    id: str; kuscia_job_id: str; status: str; job_snapshot: dict; failure_info: dict | None
    created_by: str; created_at: datetime; updated_at: datetime
    idempotency_key: str | None = None
    model_config={"from_attributes":True}
