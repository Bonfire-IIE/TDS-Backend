"""allow descriptive Kuscia master statuses

Revision ID: fb1c2d3e4f5a
Revises: fa0b1c2d3e4f
"""
from alembic import op
import sqlalchemy as sa

revision = "fb1c2d3e4f5a"
down_revision = "fa0b1c2d3e4f"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.alter_column("kuscia_master", "status", type_=sa.String(32), existing_type=sa.String(16), existing_nullable=False)

def downgrade() -> None:
    op.alter_column("kuscia_master", "status", type_=sa.String(16), existing_type=sa.String(32), existing_nullable=False)
