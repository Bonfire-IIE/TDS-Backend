"""store all Kuscia Master host ports

Revision ID: fd3e4f5a6b7c
Revises: fc2d3e4f5a6b
"""
from alembic import op
import sqlalchemy as sa

revision = "fd3e4f5a6b7c"
down_revision = "fc2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # api_port 已存在。其余端口用 Kuscia 1.2 脚本默认宿主端口回填旧记录。
    for name, default in (
        ("auth_port", "13081"),
        ("grpc_port", "13083"),
        ("app_port", "13080"),
        ("metrics_port", "13084"),
    ):
        op.add_column(
            "kuscia_master",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
        op.alter_column("kuscia_master", name, server_default=None)


def downgrade() -> None:
    for name in ("metrics_port", "app_port", "grpc_port", "auth_port"):
        op.drop_column("kuscia_master", name)
