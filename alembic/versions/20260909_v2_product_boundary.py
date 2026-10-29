"""Remove execution-system fields from data products."""
from alembic import op
import sqlalchemy as sa

revision = "20260909_v2_product_boundary"
down_revision = "20260909_v2_capability_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("data_product", "kuscia_domain_id")
    op.alter_column("connector", "kuscia_domain_id", existing_type=sa.String(63), nullable=True)
    op.alter_column("data_catalog", "kuscia_domain_id", existing_type=sa.String(63), nullable=True)


def downgrade() -> None:
    raise RuntimeError("destructive V2 boundary migration cannot be downgraded")
