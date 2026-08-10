"""add project DomainData lineage"""
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "data_lineage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("output_resource_id", sa.String(36), sa.ForeignKey("data_catalog.id"), nullable=False),
        sa.Column("input_resource_id", sa.String(36), sa.ForeignKey("data_catalog.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("project_run_id", sa.String(36), sa.ForeignKey("project_run.id"), nullable=False),
        sa.Column("workflow_node_id", sa.String(40), nullable=False),
        sa.Column("output_port", sa.String(64), nullable=False),
        sa.Column("app_image_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for col in ("output_resource_id", "input_resource_id", "project_id", "project_run_id"):
        op.create_index(f"ix_data_lineage_{col}", "data_lineage", [col])

def downgrade():
    op.drop_table("data_lineage")
