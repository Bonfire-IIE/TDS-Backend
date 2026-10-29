"""Make center-created resources usable when their connector data source is synced."""

from alembic import op


revision = "20260917_sync_resource_bindings"
down_revision = ("20260914_kuscia_app_mapping", "20260915_workflow_tables")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE data_resource_binding AS binding
        SET connector_resource_ref = binding.platform_resource_id,
            sync_status = 'synced',
            last_synced_at = now(),
            updated_at = now()
        FROM data_catalog AS resource
        JOIN data_source AS datasource
          ON datasource.id = resource.datasource_id
         AND datasource.connector_id = resource.provider_connector_id
        WHERE binding.platform_resource_id = resource.id
          AND binding.connector_id = resource.provider_connector_id
          AND binding.source = 'platform'
          AND binding.sync_status = 'pending'
          AND binding.connector_resource_ref IS NULL
          AND datasource.external_source_ref IS NOT NULL
        """
    )


def downgrade() -> None:
    # A synced generic binding is valid connector state and must not be made
    # unusable merely because application code is rolled back.
    pass
