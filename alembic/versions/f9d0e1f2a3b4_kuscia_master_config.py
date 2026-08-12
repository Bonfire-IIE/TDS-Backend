"""extend Kuscia master connection metadata"""
from alembic import op
import sqlalchemy as sa
revision = "f9d0e1f2a3b4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None
def upgrade():
    for name, typ in (("scheme", sa.String(8)), ("deploy_endpoint", sa.String(255)), ("credential_ref", sa.String(512)), ("status", sa.String(16)), ("last_checked_at", sa.DateTime(timezone=True)), ("last_error", sa.String(1000))):
        op.add_column("kuscia_master", sa.Column(name, typ, nullable=True))
    op.execute("UPDATE kuscia_master SET scheme='https', status='unconfigured' WHERE scheme IS NULL")
def downgrade():
    for name in ("last_error", "last_checked_at", "status", "credential_ref", "deploy_endpoint", "scheme"): op.drop_column("kuscia_master", name)
