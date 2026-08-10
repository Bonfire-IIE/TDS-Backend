"""catalog product soft delete

Revision ID: a1b2c3d4e5f6
Revises: f7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("data_catalog", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("data_product", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("data_product", "deleted_at")
    op.drop_column("data_catalog", "deleted_at")
