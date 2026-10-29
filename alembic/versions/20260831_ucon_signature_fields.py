"""Store real contract signatures and connector identity fingerprints."""
from alembic import op
import sqlalchemy as sa
revision = "20260831_ucon_signature_fields"
down_revision = "20260831_ucon_signing"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("contract_party", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column("contract_party", sa.Column("signature_algorithm", sa.String(32), nullable=True))
    op.add_column("contract_party", sa.Column("signing_key_id", sa.String(64), nullable=True))
    op.add_column("contract_party", sa.Column("connector_cert_fingerprint", sa.String(64), nullable=True))
def downgrade():
    for name in ("connector_cert_fingerprint", "signing_key_id", "signature_algorithm", "signature"):
        op.drop_column("contract_party", name)
