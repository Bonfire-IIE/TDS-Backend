"""data grant tracking

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "data_grant",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_run_id", sa.String(36), nullable=False),
        sa.Column("domain_id", sa.String(63), nullable=False),
        sa.Column("domaindata_id", sa.String(63), nullable=False),
        sa.Column("grant_domain", sa.String(63), nullable=False),
        sa.Column("kuscia_grant_id", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_data_grant_project_run_id", "data_grant", ["project_run_id"])

def downgrade():
    op.drop_table("data_grant")
