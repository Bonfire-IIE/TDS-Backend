"""Destructive rebuild of resource/product business boundaries."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_res_product"
down_revision = "20260921_execution_signatures"
branch_labels = None
depends_on = None

def _add(table, column):
    op.add_column(table, column)

def upgrade() -> None:
    # The request explicitly permits destructive migration; old directory and
    # product rows must not survive with incompatible semantics.
    op.execute("DELETE FROM data_resource_binding")
    op.execute("DELETE FROM data_product")
    op.execute("DELETE FROM data_catalog")
    op.alter_column("data_catalog", "security_level", existing_type=sa.String(4), type_=sa.String(16), nullable=False)
    op.alter_column("data_catalog", "status", existing_type=sa.String(16), type_=sa.String(24), nullable=False)
    op.alter_column("data_catalog", "update_freq", existing_type=sa.String(8), type_=sa.String(16), nullable=True)
    op.alter_column("data_product", "status", existing_type=sa.String(16), type_=sa.String(24), nullable=False)
    op.alter_column("data_product", "resource_id", existing_type=sa.String(36), nullable=True)
    op.alter_column("data_product", "provider_connector_id", existing_type=sa.String(36), nullable=True)
    _add("data_catalog", sa.Column("industry_code", sa.String(8), nullable=False, server_default=""))
    _add("data_catalog", sa.Column("theme_code", sa.String(16), nullable=True))
    for name, length in (("resource_owner_name",128),("resource_owner_id",64),("contact_name",64),("contact_information",128)):
        _add("data_catalog", sa.Column(name, sa.String(length), nullable=False, server_default=""))
    _add("data_catalog", sa.Column("resource_abstract", sa.Text(), nullable=False, server_default=""))
    _add("data_catalog", sa.Column("resource_format", sa.String(64), nullable=False, server_default=""))
    _add("data_catalog", sa.Column("update_method", sa.String(16), nullable=True))
    _add("data_catalog", sa.Column("data_size", sa.String(128), nullable=True))
    _add("data_catalog", sa.Column("time_range", sa.String(64), nullable=True))
    _add("data_catalog", sa.Column("personal_information_level", sa.String(16), nullable=False, server_default="none"))
    _add("data_catalog", sa.Column("resource_quality", sa.String(16), nullable=True))
    _add("data_catalog", sa.Column("high_quality_flag", sa.String(16), nullable=True))
    _add("data_catalog", sa.Column("data_modalities", sa.JSON(), nullable=True))
    _add("data_catalog", sa.Column("contains_synthetic_data", sa.Boolean(), nullable=True))
    _add("data_catalog", sa.Column("ai_readiness", sa.String(16), nullable=True))
    _add("data_catalog", sa.Column("ai_task_types", sa.JSON(), nullable=True))
    _add("data_catalog", sa.Column("annotation_info", sa.JSON(), nullable=True))
    _add("data_catalog", sa.Column("ai_training_authorization", sa.String(32), nullable=True))
    _add("data_catalog", sa.Column("review_comment", sa.Text(), nullable=True))
    _add("data_product", sa.Column("product_type", sa.String(16), nullable=False, server_default="dataset"))
    _add("data_product", sa.Column("industry_code", sa.String(8), nullable=False, server_default=""))
    _add("data_product", sa.Column("region_code", sa.String(16), nullable=True))
    _add("data_product", sa.Column("personal_information_level", sa.String(16), nullable=False, server_default="none"))
    _add("data_product", sa.Column("delivery_method", sa.String(16), nullable=False, server_default="other"))
    _add("data_product", sa.Column("usage_limitations", sa.Text(), nullable=False, server_default=""))
    _add("data_product", sa.Column("authorization_required", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add("data_product", sa.Column("data_subject_type", sa.String(16), nullable=False, server_default="enterprise"))
    _add("data_product", sa.Column("data_size", sa.String(64), nullable=True))
    _add("data_product", sa.Column("update_frequency", sa.String(16), nullable=True))
    _add("data_product", sa.Column("applicable_model_types", sa.JSON(), nullable=True))
    _add("data_product", sa.Column("ai_usage_scenarios", sa.JSON(), nullable=True))
    _add("data_product", sa.Column("provider_name", sa.String(128), nullable=False, server_default=""))
    _add("data_product", sa.Column("provider_type", sa.String(16), nullable=False, server_default="法人"))
    _add("data_product", sa.Column("provider_identity_id", sa.String(64), nullable=False, server_default=""))
    _add("data_product", sa.Column("provider_description", sa.Text(), nullable=False, server_default=""))
    _add("data_product", sa.Column("declarations", sa.JSON(), nullable=True))
    op.create_table("data_product_resource",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("data_product.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("data_catalog.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="input"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("processing_description", sa.Text(), nullable=True),
        sa.Column("authorization_scope", sa.Text(), nullable=True),
        sa.UniqueConstraint("product_id", "resource_id", name="uq_product_resource"))
    op.execute("UPDATE data_catalog SET status='pending_review', security_level='general_1'")
    op.execute("UPDATE data_product SET status='listed'")

def downgrade() -> None:
    raise RuntimeError("destructive resource/product rebuild cannot be downgraded")
