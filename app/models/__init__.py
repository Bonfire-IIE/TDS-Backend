"""ORM 模型聚合导入（供 Alembic autogenerate 发现全部表）。"""
from app.models.appimage import AppImage
from app.models.catalog import CatalogCodeDict, DataCatalog
from app.models.connector import Connector
from app.models.contract import ContractParty, DigitalContract, NegotiationHistory
from app.models.contract_template import ContractTemplate
from app.models.datasource import DataSource
from app.models.job import Job
from app.models.product import DataProduct
from app.models.usage import UsageCounter, UsageRecord
from app.models.project import Project, WorkflowVersion, WorkflowApproval, ProjectRun, DataLineage
from app.models.data_grant import DataGrant
from app.models.audit import AuditEvent, AuditOutbox, AuditAnchor
from app.models.kuscia_master import KusciaMaster

__all__ = [
    "AppImage",
    "Connector",
    "Job",
    "DataCatalog",
    "CatalogCodeDict",
    "DataSource",
    "DataProduct",
    "DigitalContract",
    "ContractParty",
    "NegotiationHistory",
    "ContractTemplate",
    "UsageCounter",
    "UsageRecord",
    "Project", "WorkflowVersion", "WorkflowApproval", "ProjectRun", "DataLineage",
    "DataGrant",
    "AuditEvent", "AuditOutbox", "AuditAnchor", "KusciaMaster",
]
