"""add structured Kuscia failure summary to jobs"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e5a51d6c816b"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("job", sa.Column("failure_info", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("job", "failure_info")
