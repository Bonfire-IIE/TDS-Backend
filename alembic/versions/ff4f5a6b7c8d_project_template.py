"""add project workflow templates"""
from alembic import op
import sqlalchemy as sa

revision = "ff4f5a6b7c8d"
down_revision = "fe4f5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_template",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workflow", sa.JSON(), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_template_owner", "project_template", ["owner"])


def downgrade():
    op.drop_index("ix_project_template_owner", table_name="project_template")
    op.drop_table("project_template")
