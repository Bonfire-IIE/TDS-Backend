from alembic import op
import sqlalchemy as sa
revision="20260903_app_definition"
down_revision="20260902_std_contract_doc"
branch_labels=None
depends_on=None
def upgrade():
 op.create_table("application_definition",sa.Column("id",sa.String(36),primary_key=True),sa.Column("key",sa.String(128),nullable=False,unique=True),sa.Column("name",sa.String(255),nullable=False),sa.Column("description",sa.Text()),sa.Column("provider",sa.String(255)),sa.Column("app_image_name",sa.String(128),nullable=False),sa.Column("workflow_template",sa.JSON(),nullable=False),sa.Column("config_schema",sa.JSON()),sa.Column("status",sa.String(16),nullable=False,server_default="published"),sa.Column("version",sa.String(32),nullable=False,server_default="1.0.0"),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False)); op.create_index("ix_application_definition_key","application_definition",["key"])
def downgrade(): op.drop_index("ix_application_definition_key",table_name="application_definition"); op.drop_table("application_definition")
