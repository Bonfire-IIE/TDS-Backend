"""Contract-bound privacy computing business objects."""
from alembic import op
import sqlalchemy as sa

revision = "20260909_v2_privacy_compute"
down_revision = "20260909_v2_product_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privacy_compute_project",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("contract_id", sa.String(47), sa.ForeignKey("digital_contract.contract_id"), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("contract_document_hash", sa.String(64), nullable=False),
        sa.Column("application_code", sa.String(128), nullable=False),
        sa.Column("configuration", sa.JSON()),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_privacy_compute_project_contract_id", "privacy_compute_project", ["contract_id"])
    op.create_index("ix_privacy_compute_project_application_code", "privacy_compute_project", ["application_code"])
    op.create_table(
        "privacy_compute_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("privacy_compute_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("system_type", sa.String(64)),
        sa.Column("external_run_ref", sa.String(255)),
        sa.Column("result", sa.JSON()),
        sa.Column("evidence", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_privacy_compute_run_idempotency"),
    )
    op.create_index("ix_privacy_compute_run_project_id", "privacy_compute_run", ["project_id"])


def downgrade() -> None:
    op.drop_table("privacy_compute_run")
    op.drop_table("privacy_compute_project")
