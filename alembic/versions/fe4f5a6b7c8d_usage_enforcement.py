"""usage-control enforcement, compensation and idempotency

Revision ID: fe4f5a6b7c8d
Revises: fd3e4f5a6b7c
"""
from alembic import op
import sqlalchemy as sa

revision = "fe4f5a6b7c8d"
down_revision = "fd3e4f5a6b7c"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("usage_record", sa.Column("obligations", sa.JSON(), nullable=True))
    op.add_column("usage_record", sa.Column("obligation_status", sa.JSON(), nullable=True))
    op.add_column("project_run", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("job", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("job", sa.Column("usage_record_ids", sa.JSON(), nullable=True))
    op.add_column("job", sa.Column("obligations", sa.JSON(), nullable=True))
    op.create_unique_constraint("uq_project_run_idempotency", "project_run", ["project_id", "idempotency_key"])
    op.create_unique_constraint("uq_job_creator_idempotency", "job", ["created_by", "idempotency_key"])

def downgrade():
    op.drop_constraint("uq_job_creator_idempotency", "job", type_="unique")
    op.drop_constraint("uq_project_run_idempotency", "project_run", type_="unique")
    op.drop_column("job", "obligations")
    op.drop_column("job", "usage_record_ids")
    op.drop_column("job", "idempotency_key")
    op.drop_column("project_run", "idempotency_key")
    op.drop_column("usage_record", "obligation_status")
    op.drop_column("usage_record", "obligations")
