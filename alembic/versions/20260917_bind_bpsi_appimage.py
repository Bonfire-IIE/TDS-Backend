"""Bind the registered Bonfire PSI AppImage to its published business app."""

from alembic import op
import sqlalchemy as sa


revision = "20260917_bind_bpsi_appimage"
down_revision = "20260917_sync_resource_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the business application reference (psi-default) and add the
    # concrete registered AppImage as implementation metadata.  This lets the
    # generic project compiler resolve the image without making the platform
    # model engine-specific.
    op.execute(sa.text("""
        UPDATE privacy_application_binding
        SET implementation_metadata = (
            COALESCE(implementation_metadata, '{}'::json)::jsonb
            || jsonb_build_object('app_image', 'bpsi-brpc-image')
        )::json
        WHERE application_code = 'APP-PSI-BREACH-CHECK'
          AND system_type = 'privacy-compute'
          AND system_application_ref = 'psi-default'
          AND status = 'published'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE privacy_application_binding
        SET implementation_metadata = (implementation_metadata::jsonb - 'app_image')::json
        WHERE application_code = 'APP-PSI-BREACH-CHECK'
          AND system_type = 'privacy-compute'
          AND system_application_ref = 'psi-default'
    """))
