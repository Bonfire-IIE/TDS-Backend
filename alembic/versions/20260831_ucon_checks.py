"""UCON stage evidence."""
from alembic import op
import sqlalchemy as sa
revision = "20260831_ucon_checks"
down_revision = "20260831_ucon_signature_fields"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("ucon_check",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("contract_id", sa.String(47), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True), sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False), sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True), sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for col in ("contract_id", "project_id", "job_id", "stage"):
        op.create_index(f"ix_ucon_check_{col}", "ucon_check", [col])
def downgrade(): op.drop_table("ucon_check")
