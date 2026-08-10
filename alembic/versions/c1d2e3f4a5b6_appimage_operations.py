"""appimage operations and uc capabilities

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("app_image", sa.Column("operations", sa.JSON(), nullable=True))
    op.add_column("app_image", sa.Column("uc_capabilities", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("app_image", "uc_capabilities")
    op.drop_column("app_image", "operations")
