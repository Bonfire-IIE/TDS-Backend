"""store connector Lite KusciaAPI endpoint"""
from alembic import op
import sqlalchemy as sa
revision = "f2a3b4c5d6e7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("connector", sa.Column("lite_api_endpoint", sa.String(255), nullable=True))
    op.add_column("connector", sa.Column("lite_api_port", sa.Integer(), nullable=True))
    op.execute("UPDATE connector SET lite_api_endpoint='https://127.0.0.1', lite_api_port=28081 WHERE kuscia_domain_id='alice'")
    op.execute("UPDATE connector SET lite_api_endpoint='https://127.0.0.1', lite_api_port=38081 WHERE kuscia_domain_id='bob'")
def downgrade():
    op.drop_column("connector", "lite_api_port")
    op.drop_column("connector", "lite_api_endpoint")
