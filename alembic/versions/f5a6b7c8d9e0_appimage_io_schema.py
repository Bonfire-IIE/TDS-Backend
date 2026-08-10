"""add AppImage workflow IO schema"""
from alembic import op
import sqlalchemy as sa
revision = "f5a6b7c8d9e0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("app_image", sa.Column("io_schema", sa.JSON(), nullable=True))
def downgrade():
    op.drop_column("app_image", "io_schema")
