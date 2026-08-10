"""store imported Kuscia Master nodes"""
from alembic import op
import sqlalchemy as sa

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kuscia_master",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("deployment_ip", sa.String(45), nullable=False),
        sa.Column("api_port", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("deployment_ip", "api_port", name="uq_kuscia_master_endpoint"),
    )


def downgrade():
    op.drop_table("kuscia_master")
