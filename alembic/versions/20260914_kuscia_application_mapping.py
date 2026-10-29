"""Keep engine-specific application mapping out of platform bindings.

Revision ID: 20260914_kuscia_app_mapping
Revises: 20260914_dynamic_execution
"""
from alembic import op
import sqlalchemy as sa


revision = "20260914_kuscia_app_mapping"
down_revision = "20260914_dynamic_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
