"""merge current migration heads

Revision ID: fa0b1c2d3e4f
Revises: d1e2f3a4b5c6, f9d0e1f2a3b4
"""
from alembic import op

revision = "fa0b1c2d3e4f"
down_revision = ("d1e2f3a4b5c6", "f9d0e1f2a3b4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
