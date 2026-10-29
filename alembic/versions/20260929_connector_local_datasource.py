"""Move data-source ownership completely to Connector Portal."""

from alembic import op
import sqlalchemy as sa


revision = "20260929_local_datasource"
down_revision = "20260922_product_standard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_catalog", sa.Column("datasource_name", sa.String(128), nullable=True))
    op.add_column("data_catalog", sa.Column("datasource_type", sa.String(16), nullable=True))
    op.add_column("data_catalog", sa.Column("datasource_uri", sa.String(512), nullable=True))
    op.execute(sa.text("""
        UPDATE data_catalog
        SET datasource_name = (SELECT name FROM data_source WHERE data_source.id = data_catalog.datasource_id),
            datasource_type = (SELECT type FROM data_source WHERE data_source.id = data_catalog.datasource_id),
            datasource_uri = (SELECT uri FROM data_source WHERE data_source.id = data_catalog.datasource_id),
            datasource_id = COALESCE(
                (SELECT external_source_ref FROM data_source WHERE data_source.id = data_catalog.datasource_id),
                datasource_id
            )
        WHERE EXISTS (SELECT 1 FROM data_source WHERE data_source.id = data_catalog.datasource_id)
    """))
    op.drop_table("data_source")


def downgrade() -> None:
    op.create_table(
        "data_source",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("connector_id", sa.String(36), nullable=False),
        sa.Column("external_source_ref", sa.String(255), nullable=True),
        sa.Column("uri", sa.String(512), nullable=True),
        sa.Column("info", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.drop_column("data_catalog", "datasource_uri")
    op.drop_column("data_catalog", "datasource_type")
    op.drop_column("data_catalog", "datasource_name")
