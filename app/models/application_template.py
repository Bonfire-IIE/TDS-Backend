"""Immutable job-template versions and project-scoped delegated execution."""
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

def uid(): return str(uuid.uuid4())

class ApplicationTemplate(Base):
    __tablename__ = 'application_template'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255))
    draft: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ApplicationTemplateVersion(Base):
    __tablename__ = 'application_template_version'
    __table_args__ = (UniqueConstraint('application_id','version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    application_id: Mapped[str] = mapped_column(ForeignKey('application_template.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    definition_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='published')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ComputationDelegation(Base):
    __tablename__ = 'computation_delegation'
    __table_args__ = (UniqueConstraint('project_id','version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('project.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    scope: Mapped[dict] = mapped_column(JSON)
    scope_hash: Mapped[str] = mapped_column(String(64))
    contract_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='pending')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class DelegationDecision(Base):
    __tablename__ = 'delegation_decision'
    __table_args__ = (UniqueConstraint('delegation_id','connector_id','kind'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    delegation_id: Mapped[str] = mapped_column(ForeignKey('computation_delegation.id'), index=True)
    connector_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(16))  # business / service
    decision: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ExecutionIdentity(Base):
    """Operator-verified organizational identity, separate from the login owner."""
    __tablename__ = 'execution_identity'
    connector_id: Mapped[str] = mapped_column(ForeignKey('connector.id'), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default='verified')
    verified_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
