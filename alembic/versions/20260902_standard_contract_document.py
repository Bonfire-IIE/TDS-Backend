"""store standard digital contract document"""
from alembic import op
import sqlalchemy as sa
revision = "20260902_std_contract_doc"
down_revision = "20260831_connector_cert_fp"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("digital_contract", sa.Column("standard_document", sa.JSON(), nullable=True))
def downgrade():
    op.drop_column("digital_contract", "standard_document")
