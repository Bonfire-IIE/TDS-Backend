"""Add standard product registration and listing metadata."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_product_standard"
down_revision = "20260922_resource_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The preceding destructive migration leaves these columns empty, so the
    # standard code widths/defaults can be applied directly without a
    # compatibility transform.
    for name, existing, target, default in (
        ("product_type", sa.String(16), sa.String(2), "01"),
        ("personal_information_level", sa.String(16), sa.String(2), "0"),
        ("delivery_method", sa.String(16), sa.String(2), "04"),
        ("data_subject_type", sa.String(16), sa.String(2), "02"),
        ("provider_type", sa.String(16), sa.String(2), "02"),
    ):
        op.alter_column(
            "data_product", name, existing_type=existing, type_=target,
            existing_nullable=False, nullable=False, server_default=default,
        )
    op.alter_column(
        "data_product", "update_frequency", existing_type=sa.String(16),
        existing_nullable=True, nullable=False, server_default="其他",
    )
    additions = [
        sa.Column("time_range", sa.String(64), nullable=True),
        sa.Column("application_scenarios", sa.Text(), nullable=False, server_default=""),
        sa.Column("public_data", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider_entity_info", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("operator_name", sa.String(32), nullable=True),
        sa.Column("operator_telephone", sa.String(32), nullable=True),
        sa.Column("operator_id_card", sa.String(32), nullable=True),
        sa.Column("platform_name", sa.String(128), nullable=True),
        sa.Column("platform_id", sa.String(80), nullable=True),
        sa.Column("platform_location", sa.String(128), nullable=True),
        sa.Column("delivery_mode", sa.String(2), nullable=True),
        sa.Column("measure_method", sa.String(16), nullable=True),
        sa.Column("measure_unit", sa.String(16), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("delivery_info", sa.Text(), nullable=True),
    ]
    for column in additions:
        op.add_column("data_product", column)
    op.alter_column("data_product", "application_scenarios", server_default=None)
    op.alter_column("data_product", "provider_entity_info", server_default=None)


def downgrade() -> None:
    for name in ("delivery_info", "price", "measure_unit", "measure_method", "delivery_mode", "platform_location", "platform_id", "platform_name", "operator_id_card", "operator_telephone", "operator_name", "provider_entity_info", "public_data", "application_scenarios", "time_range"):
        op.drop_column("data_product", name)
