"""Replace temporary contract columns with the TC609 document aggregate."""
from alembic import op
import sqlalchemy as sa

revision = "20260903_std_contract_model"
down_revision = "20260903_app_definition"
branch_labels = None
depends_on = None

def upgrade():
    # Destructive migration explicitly requested: the standard document is the sole model.
    for col in ("name", "abstract", "purpose", "product_id", "provider_connector_id", "consumer_connector_id", "mode", "status", "policies", "allowed_appimages", "contract_hash", "standard_document"):
        op.drop_column("digital_contract", col)
    op.add_column("digital_contract", sa.Column("document", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("digital_contract", sa.Column("document_hash", sa.String(64), nullable=False, server_default=""))
    op.add_column("digital_contract", sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"))
    op.drop_table("contract_party")
    op.drop_table("negotiation_history")
    op.create_table("digital_contract_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(47), sa.ForeignKey("digital_contract.contract_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("previous_hash", sa.String(64)),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade():
    raise RuntimeError("destructive standard contract migration cannot be downgraded")
