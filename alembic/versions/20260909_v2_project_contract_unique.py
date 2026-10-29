"""Enforce one privacy-computing project per signed contract."""
from alembic import op


revision = "20260909_v2_proj_contract_uq"
down_revision = "20260909_v2_privacy_compute"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_privacy_compute_project_contract",
        "privacy_compute_project",
        ["contract_id"],
    )


def downgrade() -> None:
    raise RuntimeError("destructive V2 boundary migration cannot be downgraded")
