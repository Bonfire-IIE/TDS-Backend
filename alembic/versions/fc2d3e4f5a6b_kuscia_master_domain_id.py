"""store Kuscia Master domain id

Revision ID: fc2d3e4f5a6b
Revises: fb1c2d3e4f5a
"""
from alembic import op
import sqlalchemy as sa

revision = "fc2d3e4f5a6b"
down_revision = "fb1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 已有引导部署默认使用 bonfire-master；先以默认值安全回填已有行，随后
    # 移除数据库默认，要求所有新配置显式提交真实 domain_id。
    op.add_column(
        "kuscia_master",
        sa.Column("domain_id", sa.String(63), nullable=False, server_default="bonfire-master"),
    )
    op.alter_column("kuscia_master", "domain_id", server_default=None)


def downgrade() -> None:
    op.drop_column("kuscia_master", "domain_id")
