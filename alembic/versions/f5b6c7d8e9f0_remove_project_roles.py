"""remove project-level participant roles

Revision ID: f5b6c7d8e9f0
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa

revision = "f5b6c7d8e9f0"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_table("project_party")

def downgrade():
    op.create_table(
        "project_party",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("project_id",sa.String(36),sa.ForeignKey("project.id",ondelete="CASCADE"),nullable=False),
        sa.Column("connector_id",sa.String(36),nullable=False),
        sa.Column("domain_id",sa.String(63),nullable=False),
        sa.Column("role",sa.String(24),nullable=False),
        sa.UniqueConstraint("project_id","connector_id"),
    )
    op.create_index("ix_project_party_project_id","project_party",["project_id"])
