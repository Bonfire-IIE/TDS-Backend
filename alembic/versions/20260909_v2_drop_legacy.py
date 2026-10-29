"""Remove pre-v2 Kuscia-backed platform objects.

Revision ID: 20260909_v2_drop_legacy
Revises: 20260909_v2_generic_refs
"""
from alembic import op
import sqlalchemy as sa


revision = "20260909_v2_drop_legacy"
down_revision = "20260909_v2_generic_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("data_product", "allowed_appimages")
    for table in (
        "data_lineage",
        "data_grant",
        "workflow_approval",
        "project_run",
        "workflow_version",
        "project_party",
        "project",
        "project_template",
        "job",
        "app_image",
        "application_definition",
        "kuscia_master",
    ):
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table}"'))


def downgrade() -> None:
    raise RuntimeError("v2 legacy-object removal is irreversible; restore a database backup")
