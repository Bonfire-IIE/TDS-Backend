"""connector soft delete

Revision ID: f7b8c9d0e1f2
Revises: f5b6c7d8e9f0
"""
from alembic import op
import sqlalchemy as sa

revision = "f7b8c9d0e1f2"
down_revision = "f5b6c7d8e9f0"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("connector", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("connector", "deleted_at")
