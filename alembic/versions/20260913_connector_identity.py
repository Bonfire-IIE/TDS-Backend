"""Separate connector identity from privacy-compute engine configuration."""
from alembic import op
import sqlalchemy as sa

revision = "20260913_connector_identity"
down_revision = "20260909_v2_generic_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy rows represent Kuscia nodes rather than cryptographic connector
    # identities. They cannot be migrated without inventing a private key.
    op.execute(sa.text('TRUNCATE TABLE "connector" CASCADE'))
    for name in ("external_system_ref", "endpoint", "execution_endpoint", "execution_port", "auth_port", "grpc_port", "app_port", "data_port", "certificate_fingerprint"):
        op.drop_column("connector", name)
    op.add_column("connector", sa.Column("csr_pem", sa.Text(), nullable=False))
    op.add_column("connector", sa.Column("csr_fingerprint", sa.String(64), nullable=False))
    op.add_column("connector", sa.Column("public_key_fingerprint", sa.String(64), nullable=False))
    op.add_column("connector", sa.Column("certificate_pem", sa.Text()))
    op.add_column("connector", sa.Column("certificate_serial", sa.String(64)))
    op.add_column("connector", sa.Column("certificate_not_before", sa.DateTime(timezone=True)))
    op.add_column("connector", sa.Column("certificate_not_after", sa.DateTime(timezone=True)))
    op.add_column("connector", sa.Column("activated_at", sa.DateTime(timezone=True)))
    op.add_column("connector", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_connector_csr_fingerprint", "connector", ["csr_fingerprint"])
    op.create_unique_constraint("uq_connector_public_key_fingerprint", "connector", ["public_key_fingerprint"])
    op.create_unique_constraint("uq_connector_certificate_serial", "connector", ["certificate_serial"])
    op.add_column("connector_capability", sa.Column("adapter_type", sa.String(64)))
    op.add_column("connector_capability", sa.Column("implementation_ref", sa.String(255)))


def downgrade() -> None:
    raise RuntimeError("connector identity migration is irreversible")
