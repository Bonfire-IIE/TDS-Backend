"""Persist replay protection for connector-signed execution calls."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_execution_signatures"
down_revision = "20260917_bind_bpsi_appimage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("execution_request_nonce", sa.Column("id", sa.String(64), primary_key=True),
                    sa.Column("expires_at", sa.BigInteger(), nullable=False))
    op.create_index("ix_execution_request_nonce_expires_at", "execution_request_nonce", ["expires_at"])


def downgrade():
    op.drop_table("execution_request_nonce")
