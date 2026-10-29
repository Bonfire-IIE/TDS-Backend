"""Align resource metadata code types with the catalog standard.

Revision ID: 20260922_resource_codes
Revises: 20260921_res_product
"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_resource_codes"
down_revision = "20260921_res_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "data_catalog", "personal_information_level",
        existing_type=sa.String(16), type_=sa.String(2),
        existing_nullable=False, nullable=False, server_default="0",
    )
    op.alter_column(
        "data_catalog",
        "contains_synthetic_data",
        existing_type=sa.Boolean(),
        type_=sa.String(2),
        existing_nullable=True,
        postgresql_using=(
            "CASE WHEN contains_synthetic_data IS TRUE THEN '02' "
            "WHEN contains_synthetic_data IS FALSE THEN '01' ELSE NULL END"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "data_catalog", "personal_information_level",
        existing_type=sa.String(2), type_=sa.String(16),
        existing_nullable=False, nullable=False, server_default="none",
    )
    op.alter_column(
        "data_catalog",
        "contains_synthetic_data",
        existing_type=sa.String(2),
        type_=sa.Boolean(),
        existing_nullable=True,
        postgresql_using="CASE WHEN contains_synthetic_data IN ('02', '03') THEN TRUE ELSE FALSE END",
    )
