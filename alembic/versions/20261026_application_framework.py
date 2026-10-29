"""Application templates and delegated project execution (additive only)."""
from alembic import op
from app.models.application_template import ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation, DelegationDecision, ExecutionIdentity
revision = '20261026_app_framework'
down_revision = '20260929_local_datasource'
branch_labels = None
depends_on = None

def upgrade():
    for model in (ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation, DelegationDecision, ExecutionIdentity):
        model.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    for model in (ExecutionIdentity, DelegationDecision, ComputationDelegation, ApplicationTemplateVersion, ApplicationTemplate):
        model.__table__.drop(op.get_bind(), checkfirst=True)
