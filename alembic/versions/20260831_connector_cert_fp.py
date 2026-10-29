"""Connector certificate identity fingerprint."""
from alembic import op
import sqlalchemy as sa
revision = "20260831_connector_cert_fp"
down_revision = "20260831_ucon_checks"
branch_labels = None
depends_on = None
def upgrade(): op.add_column("connector", sa.Column("certificate_fingerprint", sa.String(64), nullable=True))
def downgrade(): op.drop_column("connector", "certificate_fingerprint")
