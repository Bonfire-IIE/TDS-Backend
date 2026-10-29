"""Remove execution-system names from business records.

Revision ID: 20260909_v2_generic_binding
Revises: 20260909_v2_drop_legacy
"""
from alembic import op
import sqlalchemy as sa


revision = "20260909_v2_generic_binding"
down_revision = "20260909_v2_drop_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE privacy_application_binding
        SET system_type = 'privacy-compute',
            system_application_ref = 'psi-default',
            implementation_metadata = '{}'::json
        WHERE application_code = 'APP-PSI-BREACH-CHECK'
    """))
    op.execute(sa.text("""
        UPDATE privacy_compute_run
        SET system_type = 'privacy-compute'
        WHERE system_type = 'kuscia-privacy-compute'
    """))


def downgrade() -> None:
    raise RuntimeError("v2 generic binding migration is irreversible")
