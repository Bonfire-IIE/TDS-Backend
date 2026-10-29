"""V2 generic connector capabilities and privacy application mappings."""
from alembic import op
import sqlalchemy as sa

revision = "20260909_v2_capability_models"
down_revision = "20260903_std_contract_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_resource_binding",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("platform_resource_id", sa.String(36), sa.ForeignKey("data_catalog.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_id", sa.String(36), sa.ForeignKey("connector.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_resource_ref", sa.String(255)),
        sa.Column("source", sa.String(16), nullable=False, server_default="platform"),
        sa.Column("version", sa.String(64)),
        sa.Column("sync_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("metadata_snapshot", sa.JSON()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform_resource_id", "connector_id", name="uq_resource_connector_binding"),
    )
    op.create_index("ix_data_resource_binding_platform_resource_id", "data_resource_binding", ["platform_resource_id"])
    op.create_index("ix_data_resource_binding_connector_id", "data_resource_binding", ["connector_id"])
    op.create_table(
        "connector_capability",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connector_id", sa.String(36), sa.ForeignKey("connector.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(64), nullable=False),
        sa.Column("capability_version", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default="declared"),
        sa.Column("evidence", sa.JSON()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("connector_id", "capability_code", name="uq_connector_capability"),
    )
    op.create_index("ix_connector_capability_connector_id", "connector_capability", ["connector_id"])
    op.create_index("ix_connector_capability_capability_code", "connector_capability", ["capability_code"])
    op.create_table(
        "privacy_application",
        sa.Column("code", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("execution_env_code", sa.String(64), nullable=False),
        sa.Column("input_schema", sa.JSON()),
        sa.Column("output_schema", sa.JSON()),
        sa.Column("extension_schema", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "privacy_application_binding",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_code", sa.String(128), sa.ForeignKey("privacy_application.code", ondelete="CASCADE"), nullable=False),
        sa.Column("system_type", sa.String(64), nullable=False),
        sa.Column("system_application_ref", sa.String(255), nullable=False),
        sa.Column("system_application_version", sa.String(64)),
        sa.Column("capability_requirements", sa.JSON()),
        sa.Column("adapter_version", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False, server_default="published"),
        sa.Column("implementation_metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_code", "system_type", "system_application_ref", name="uq_privacy_app_binding"),
    )
    op.create_index("ix_privacy_application_execution_env_code", "privacy_application", ["execution_env_code"])
    op.create_index("ix_privacy_application_binding_application_code", "privacy_application_binding", ["application_code"])
    application = sa.table(
        "privacy_application",
        sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("execution_env_code", sa.String),
        sa.column("input_schema", sa.JSON), sa.column("output_schema", sa.JSON),
        sa.column("extension_schema", sa.JSON), sa.column("status", sa.String),
        sa.column("version", sa.String), sa.column("created_by", sa.String),
    )
    op.bulk_insert(application, [{
        "code": "APP-PSI-BREACH-CHECK",
        "name": "密码泄露检测 PSI",
        "description": "通过隐私集合求交检测输入集合中的密码指纹是否出现在供方数据产品中。",
        "execution_env_code": "0601",
        "input_schema": {"roles": ["provider", "consumer"], "fields": ["fingerprint_hash"]},
        "output_schema": {"types": ["intersection_cardinality", "intersection_set", "secret_shares"]},
        "extension_schema": {"resultType": {"type": "string"}},
        "status": "published", "version": "1.0.0", "created_by": "system",
    }])
    binding = sa.table(
        "privacy_application_binding",
        sa.column("id", sa.String), sa.column("application_code", sa.String),
        sa.column("system_type", sa.String), sa.column("system_application_ref", sa.String),
        sa.column("system_application_version", sa.String), sa.column("capability_requirements", sa.JSON),
        sa.column("adapter_version", sa.String), sa.column("status", sa.String),
        sa.column("implementation_metadata", sa.JSON),
    )
    op.bulk_insert(binding, [{
        "id": "builtin-psi-breach-binding", "application_code": "APP-PSI-BREACH-CHECK",
        "system_type": "privacy-compute", "system_application_ref": "psi-default",
        "system_application_version": "1.0.0", "capability_requirements": ["PSI"],
        "adapter_version": "v2", "status": "published",
        "implementation_metadata": {},
    }])


def downgrade() -> None:
    op.drop_table("data_resource_binding")
    op.drop_table("privacy_application_binding")
    op.drop_table("privacy_application")
    op.drop_table("connector_capability")
