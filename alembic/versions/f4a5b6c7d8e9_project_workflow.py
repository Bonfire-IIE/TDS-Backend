"""project workflow and runs"""
from alembic import op
import sqlalchemy as sa
revision = "f4a5b6c7d8e9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("project", sa.Column("id",sa.String(36),primary_key=True),sa.Column("name",sa.String(255),nullable=False),sa.Column("description",sa.Text()),sa.Column("contract_id",sa.String(47),nullable=False),sa.Column("initiator_connector_id",sa.String(36),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("current_version",sa.Integer()),sa.Column("created_by",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False))
    op.create_index("ix_project_contract_id","project",["contract_id"])
    op.create_table("project_party",sa.Column("id",sa.String(36),primary_key=True),sa.Column("project_id",sa.String(36),sa.ForeignKey("project.id",ondelete="CASCADE"),nullable=False),sa.Column("connector_id",sa.String(36),nullable=False),sa.Column("domain_id",sa.String(63),nullable=False),sa.Column("role",sa.String(24),nullable=False),sa.UniqueConstraint("project_id","connector_id"))
    op.create_index("ix_project_party_project_id","project_party",["project_id"])
    op.create_table("workflow_version",sa.Column("id",sa.String(36),primary_key=True),sa.Column("project_id",sa.String(36),sa.ForeignKey("project.id",ondelete="CASCADE"),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("workflow",sa.JSON(),nullable=False),sa.Column("workflow_hash",sa.String(64),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("created_by",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),sa.UniqueConstraint("project_id","version"))
    op.create_index("ix_workflow_version_project_id","workflow_version",["project_id"])
    op.create_table("workflow_approval",sa.Column("id",sa.String(36),primary_key=True),sa.Column("workflow_version_id",sa.String(36),sa.ForeignKey("workflow_version.id",ondelete="CASCADE"),nullable=False),sa.Column("connector_id",sa.String(36),nullable=False),sa.Column("decision",sa.String(16),nullable=False),sa.Column("comment",sa.Text()),sa.Column("decided_by",sa.String(64),nullable=False),sa.Column("decided_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),sa.UniqueConstraint("workflow_version_id","connector_id"))
    op.create_index("ix_workflow_approval_version","workflow_approval",["workflow_version_id"])
    op.create_table("project_run",sa.Column("id",sa.String(36),primary_key=True),sa.Column("project_id",sa.String(36),sa.ForeignKey("project.id",ondelete="CASCADE"),nullable=False),sa.Column("workflow_version_id",sa.String(36),nullable=False),sa.Column("kuscia_job_id",sa.String(64),nullable=False,unique=True),sa.Column("status",sa.String(24),nullable=False),sa.Column("job_snapshot",sa.JSON(),nullable=False),sa.Column("failure_info",sa.JSON()),sa.Column("created_by",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False))
    op.create_index("ix_project_run_project_id","project_run",["project_id"])
def downgrade():
    for table in ("project_run","workflow_approval","workflow_version","project_party","project"): op.drop_table(table)
