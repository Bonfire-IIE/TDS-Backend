"""ucon user signing keys"""
from alembic import op
import sqlalchemy as sa
revision = "20260831_ucon_signing"
down_revision = "ff4f5a6b7c8d"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("user_signing_key",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False), sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("public_key_pem", sa.String(2048), nullable=False), sa.Column("public_key_sha256", sa.String(64), nullable=False),
        sa.Column("private_key_ref", sa.String(512), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_signing_key_subject", "user_signing_key", ["subject"], unique=True)
    op.create_unique_constraint("uq_user_signing_key_key_id", "user_signing_key", ["key_id"])
def downgrade():
    op.drop_table("user_signing_key")
