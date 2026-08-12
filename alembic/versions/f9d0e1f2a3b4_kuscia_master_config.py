"""extend Kuscia master connection metadata"""
from alembic import op
import sqlalchemy as sa
revision = "f9d0e1f2a3b4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
# Kuscia Master 表由并行审计分支中的 b9c0… 创建。没有此显式依赖时，
# 全新数据库可能先执行本迁移，导致 ALTER TABLE kuscia_master 失败。
depends_on = "b9c0d1e2f3a4"
def upgrade():
    for name, typ in (("scheme", sa.String(8)), ("deploy_endpoint", sa.String(255)), ("credential_ref", sa.String(512)), ("status", sa.String(16)), ("last_checked_at", sa.DateTime(timezone=True)), ("last_error", sa.String(1000))):
        op.add_column("kuscia_master", sa.Column(name, typ, nullable=True))
    op.execute("UPDATE kuscia_master SET scheme='https', status='unconfigured' WHERE scheme IS NULL")
def downgrade():
    for name in ("last_error", "last_checked_at", "status", "credential_ref", "deploy_endpoint", "scheme"): op.drop_column("kuscia_master", name)
