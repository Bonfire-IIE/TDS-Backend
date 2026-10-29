"""Restore platform workflow and AppImage template tables.

These are platform business objects; engine-specific objects are intentionally
kept out of the schema.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260915_workflow_tables"
down_revision = "20260914_dynamic_execution"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("app_image",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(128), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False), sa.Column("description", sa.Text), sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("operations", sa.JSON), sa.Column("uc_capabilities", sa.JSON), sa.Column("image_name", sa.String(512), nullable=False), sa.Column("image_tag", sa.String(128), nullable=False),
        sa.Column("registry_source", sa.String(16), server_default="third_party", nullable=False), sa.Column("registry", sa.String(255)),
        sa.Column("deploy_templates", sa.JSON), sa.Column("config_templates", sa.JSON), sa.Column("job_template", sa.JSON), sa.Column("io_schema", sa.JSON), sa.Column("party_schema", sa.JSON), sa.Column("parameter_schema", sa.JSON), sa.Column("ui_schema", sa.JSON), sa.Column("task_input_template", sa.JSON),
        sa.Column("status", sa.String(16), server_default="registered", nullable=False), sa.Column("scope", sa.String(16), server_default="custom", nullable=False), sa.Column("created_by", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("project",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text), sa.Column("contract_id", sa.String(47), nullable=False), sa.Column("initiator_connector_id", sa.String(36), nullable=False), sa.Column("status", sa.String(24), server_default="draft"), sa.Column("current_version", sa.Integer), sa.Column("created_by", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_project_contract_id", "project", ["contract_id"])
    op.create_table("workflow_version", sa.Column("id", sa.String(36), primary_key=True), sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer, nullable=False), sa.Column("workflow", sa.JSON, nullable=False), sa.Column("workflow_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(24), server_default="pending_approval"), sa.Column("created_by", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("project_id", "version"))
    op.create_table("workflow_approval", sa.Column("id", sa.String(36), primary_key=True), sa.Column("workflow_version_id", sa.String(36), sa.ForeignKey("workflow_version.id", ondelete="CASCADE"), nullable=False), sa.Column("connector_id", sa.String(36), nullable=False), sa.Column("decision", sa.String(16), nullable=False), sa.Column("comment", sa.Text), sa.Column("decided_by", sa.String(64), nullable=False), sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("workflow_version_id", "connector_id"))
    op.create_table("project_run", sa.Column("id", sa.String(36), primary_key=True), sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False), sa.Column("workflow_version_id", sa.String(36), nullable=False), sa.Column("kuscia_job_id", sa.String(64), unique=True, nullable=False), sa.Column("status", sa.String(24), server_default="pending-dispatch"), sa.Column("job_snapshot", sa.JSON, nullable=False), sa.Column("failure_info", sa.JSON), sa.Column("created_by", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))

def downgrade() -> None:
    for table in ("project_run", "workflow_approval", "workflow_version", "project", "app_image"):
        op.drop_table(table)
