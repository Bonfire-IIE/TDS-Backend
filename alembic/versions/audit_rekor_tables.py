"""audit event chain and Rekor outbox"""
from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("audit_event",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False), sa.Column("stream_id", sa.String(255), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("actor", sa.JSON(), nullable=True), sa.Column("resource_type", sa.String(128), nullable=True), sa.Column("resource_id", sa.String(255), nullable=True), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("previous_hash", sa.String(64), nullable=False), sa.Column("current_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("stream_id", "sequence"))
    op.create_index("ix_audit_event_stream", "audit_event", ["stream_id", "sequence"])
    op.create_table("audit_outbox", sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_id", sa.String(36), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True), sa.Column("last_error", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_table("audit_anchor", sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_id", sa.String(36), nullable=False, unique=True), sa.Column("provider", sa.String(32), nullable=False), sa.Column("rekor_uuid", sa.String(255), nullable=True), sa.Column("log_index", sa.Integer(), nullable=True), sa.Column("integrated_time", sa.Integer(), nullable=True), sa.Column("entry_body", sa.Text(), nullable=True), sa.Column("inclusion_proof", sa.JSON(), nullable=True), sa.Column("checkpoint", sa.JSON(), nullable=True), sa.Column("verification_status", sa.String(24), nullable=False), sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_table("audit_anchor"); op.drop_table("audit_outbox"); op.drop_index("ix_audit_event_stream", table_name="audit_event"); op.drop_table("audit_event")
