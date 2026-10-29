"""Remove Kuscia-specific columns from core resource and connector tables."""
from alembic import op
import sqlalchemy as sa

revision = "20260909_v2_generic_refs"
down_revision = "20260909_v2_proj_contract_uq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("connector", "kuscia_domain_id", new_column_name="external_system_ref", existing_type=sa.String(63), type_=sa.String(255), nullable=True)
    op.alter_column("connector", "lite_api_endpoint", new_column_name="execution_endpoint", existing_type=sa.String(255), nullable=True)
    op.alter_column("connector", "lite_api_port", new_column_name="execution_port", existing_type=sa.Integer(), nullable=True)
    op.drop_column("data_catalog", "kuscia_domain_id")
    op.drop_column("data_catalog", "kuscia_domaindata_id")
    op.alter_column("data_source", "kuscia_datasource_id", new_column_name="external_source_ref", existing_type=sa.String(64), type_=sa.String(255), nullable=True)
    op.drop_column("data_source", "kuscia_domain_id")


def downgrade() -> None:
    raise RuntimeError("destructive V2 boundary migration cannot be downgraded")
