"""Declare runtime formats in application bindings.

Revision ID: 20260914_dynamic_execution
Revises: 20260913_connector_identity
"""
from alembic import op
import sqlalchemy as sa


revision = "20260914_dynamic_execution"
down_revision = "20260913_connector_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is data for the bundled PSI adapter, not a platform-wide default.
    op.execute(sa.text("""
        UPDATE privacy_application_binding
        SET implementation_metadata = json_build_object(
            'input_format', 'csv',
            'output_format', 'csv'
        )
        WHERE system_application_ref = 'psi-default'
          AND system_type = 'privacy-compute'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE privacy_application_binding
        SET implementation_metadata = '{}'::json
        WHERE system_application_ref = 'psi-default'
          AND system_type = 'privacy-compute'
    """))
