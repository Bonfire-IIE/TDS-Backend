"""store all connector deployment ports"""
from alembic import op
import sqlalchemy as sa
revision = "f3a4b5c6d7e8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None
def upgrade():
    for name in ("auth_port", "grpc_port", "app_port", "data_port"):
        op.add_column("connector", sa.Column(name, sa.Integer(), nullable=True))
    op.execute("UPDATE connector SET auth_port=1080, grpc_port=8083, app_port=80, data_port=9091")
def downgrade():
    for name in ("data_port", "app_port", "grpc_port", "auth_port"):
        op.drop_column("connector", name)
