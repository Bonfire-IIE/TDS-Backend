"""Project workflow, immutable versions, approvals and Kuscia run snapshots."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

def _id(): return str(uuid.uuid4())

class Project(Base):
    __tablename__ = "project"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_id: Mapped[str] = mapped_column(String(47), index=True)
    initiator_connector_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class WorkflowVersion(Base):
    __tablename__ = "workflow_version"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    workflow: Mapped[dict] = mapped_column(JSON)
    workflow_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending_approval")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class WorkflowApproval(Base):
    __tablename__ = "workflow_approval"
    __table_args__ = (UniqueConstraint("workflow_version_id", "connector_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    workflow_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflow_version.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[str] = mapped_column(String(36))
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProjectRun(Base):
    __tablename__ = "project_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id", ondelete="CASCADE"), index=True)
    workflow_version_id: Mapped[str] = mapped_column(String(36))
    kuscia_job_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    job_snapshot: Mapped[dict] = mapped_column(JSON)
    failure_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class DataLineage(Base):
    """项目作业产生的 DomainData 与输入资源之间的血缘。"""
    __tablename__ = "data_lineage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    output_resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_catalog.id"), index=True)
    input_resource_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_catalog.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id"), index=True)
    project_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("project_run.id"), index=True)
    workflow_node_id: Mapped[str] = mapped_column(String(40))
    output_port: Mapped[str] = mapped_column(String(64))
    app_image_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
