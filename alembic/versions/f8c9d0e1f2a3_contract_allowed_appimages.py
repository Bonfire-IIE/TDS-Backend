"""contract allowed appimages"""
from alembic import op
import sqlalchemy as sa
revision = "f8c9d0e1f2a3"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None
def upgrade(): op.add_column("digital_contract", sa.Column("allowed_appimages", sa.JSON(), nullable=True))
def downgrade(): op.drop_column("digital_contract", "allowed_appimages")
