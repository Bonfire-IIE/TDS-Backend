"""ORM 模型聚合导入（供 Alembic autogenerate 发现全部表）。"""
from app.models.catalog import CatalogCodeDict, DataCatalog
from app.models.connector import Connector
from app.models.execution_auth import ExecutionRequestNonce
from app.models.contract import DigitalContract, DigitalContractVersion
from app.models.contract_template import ContractTemplate
from app.models.product import DataProduct, DataProductResource
from app.models.usage import UsageCounter, UsageRecord
from app.models.audit import AuditEvent, AuditOutbox, AuditAnchor
from app.models.signing import UserSigningKey
from app.models.ucon import UconCheck
from app.models.capability import ConnectorCapability, DataResourceBinding, PrivacyApplication, PrivacyApplicationBinding
from app.models.privacy_compute import PrivacyComputeProject, PrivacyComputeRun
from app.models.appimage import AppImage
from app.models.project import Project, WorkflowVersion, WorkflowApproval, ProjectRun, DataLineage
from app.models.data_grant import DataGrant
from app.models.job import Job

__all__ = [
    "Connector",
    "DataCatalog",
    "CatalogCodeDict",
    "DataProduct",
    "DataProductResource",
    "DigitalContract",
    "DigitalContractVersion",
    "ContractTemplate",
    "UsageCounter",
    "UsageRecord",
    "AuditEvent", "AuditOutbox", "AuditAnchor", "UserSigningKey", "UconCheck",
    "ConnectorCapability", "PrivacyApplication", "PrivacyApplicationBinding",
    "DataResourceBinding",
    "PrivacyComputeProject", "PrivacyComputeRun",
    "AppImage", "Project", "WorkflowVersion", "WorkflowApproval", "ProjectRun", "DataLineage", "DataGrant", "Job",
]

from app.models.application_template import ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation, DelegationDecision, ExecutionIdentity
