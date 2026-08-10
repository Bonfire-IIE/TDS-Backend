"""add AppImage workflow contract schemas"""
from alembic import op
import sqlalchemy as sa
revision="f6a7b8c9d0e1"
down_revision="f5a6b7c8d9e0"
branch_labels=None
depends_on=None
def upgrade():
    for name in ("party_schema","parameter_schema","ui_schema","task_input_template"):
        op.add_column("app_image",sa.Column(name,sa.JSON(),nullable=True))
def downgrade():
    for name in ("task_input_template","ui_schema","parameter_schema","party_schema"):
        op.drop_column("app_image",name)
