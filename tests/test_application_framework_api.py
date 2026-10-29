"""HTTP regression tests for application authoring and project delegations.

The router runs unchanged against a fresh SQLite database. Only authentication and
session dependencies are replaced; project visibility and all authorization,
validation, identity and delegation decisions use their production code paths.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.security import get_current_user
from app.models import AppImage, Connector, DigitalContract, Project
from app.models.application_template import (
    ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation,
    DelegationDecision, ExecutionIdentity,
)
from app.routers.application_templates import router
from app.services.application_template import check_definition, digest, approved_services


@pytest.fixture
def env():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    for cid, owner in [('provider', 'provider'), ('consumer', 'consumer'), ('c1', 'svc1'), ('c2', 'svc2'), ('c3', 'svc3'), ('other', 'outsider')]:
        db.add(Connector(id=cid, name=cid, org_name='Institution '+cid, created_by=owner, status='active', csr_pem=cid, csr_fingerprint=cid, public_key_fingerprint=cid))
        db.add(ExecutionIdentity(connector_id=cid, subject_id='institution:'+cid, status='verified', verified_by='operator'))
    db.add(AppImage(id='component', name='api-component', display_name='API test component', capability='mpc', image_name='example/component', image_tag='1', created_by='operator', status='registered', scope='custom', deploy_templates=[{'role': r} for r in ['owner', 'p0', 'p1', 'p2']], party_schema={'architectures': ['cs', 'outsourced'], 'roles': [{'name': r, 'min': 1, 'max': 1} for r in ['owner', 'p0', 'p1', 'p2']]}, io_schema={'inputs': [], 'outputs': [{'name': 'result', 'kind': 'file', 'formats': ['bin'], 'role': 'owner'}]}, parameter_schema={'type': 'object', 'properties': {'size': {'type': 'integer', 'minimum': 1}}, 'required': ['size']}, task_input_template={'size': '{{parameters.size}}'}))
    document = {'contractInfo': {'expansionItem': {'computationOutsourcing': {'allowed': True}}}, 'contractPolicies': [{'executionNodeInfo': {'providerNodeId': 'provider', 'consumerNodeId': 'consumer'}, 'subjectInfo': {'dataProductId': 'product'}}]}
    db.add(DigitalContract(contract_id='contract', document=document, document_hash='contract-hash', created_by='provider'))
    db.add(Project(id='project', name='Delegation project', contract_id='contract', initiator_connector_id='consumer', created_by='consumer'))
    definition = {'architecture': 'outsourced', 'parameter_schema': {'type': 'object', 'properties': {'batch': {'type': 'integer', 'minimum': 1, 'default': 64}}}, 'roles': [{'name': 'owner', 'source': 'provider'}]+[{'name': 'compute'+str(n+1), 'source': 'delegate:'+str(n)} for n in range(3)], 'distinct_roles': [['compute1', 'compute2', 'compute3']], 'tasks': [{'id': 'compute', 'app_image': 'api-component', 'roles': {'owner': 'owner', 'p0': 'compute1', 'p1': 'compute2', 'p2': 'compute3'}, 'parameters': {'size': {'parameter': 'batch'}}}], 'inputs': [], 'outputs': [{'name': 'result', 'task': 'compute', 'port': 'result'}], 'edges': []}
    for role in definition['roles']: role['title'] = role['name']
    for port in definition['outputs']: port['title'] = port['name']
    db.commit()
    published = check_definition(db, definition)
    db.add(ApplicationTemplate(id='application', name='Inference', draft=definition, created_by='author'))
    db.add(ApplicationTemplateVersion(id='version', application_id='application', version=1, definition=published, definition_hash=digest(published)))
    db.add(ApplicationTemplate(id='private-draft', name='Unpublished', draft=definition, created_by='author'))
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    def identity(x_test_user: str = Header(default='consumer')):
        return {'username': x_test_user, 'roles': ['operator'] if x_test_user == 'operator' else []}
    app.dependency_overrides[get_current_user] = identity
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, db, definition
    db.close()
    engine.dispose()


def headers(user):
    return {'X-Test-User': user}


def delegation_body():
    return {'instances': [{'id': 'inference', 'version_id': 'version'}], 'participants': [{'connector_id': 'c'+str(n), 'roles': ['compute'+str(n)]} for n in range(1, 4)], 'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}


def issue(env):
    client, _, _ = env
    response = client.post('/projects/project/delegations', json=delegation_body(), headers=headers('consumer'))
    assert response.status_code == 201, response.text
    return response.json()['data']


def decide(client, did, cid, owner, decision='accepted'):
    return client.post('/computation-delegations/'+did+'/decision', json={'connector_id': cid, 'decision': decision}, headers=headers(owner))


def activate(env):
    d = issue(env)
    client = env[0]
    for cid, owner in [('provider', 'provider'), ('c1', 'svc1'), ('c2', 'svc2'), ('c3', 'svc3')]:
        response = decide(client, d['id'], cid, owner)
        assert response.status_code == 200, response.text
    assert response.json()['data']['status'] == 'active'
    return d


def test_authoring_permissions_and_private_draft_visibility(env):
    client, _, definition = env
    body = {'name': 'Edited inference', 'draft': definition}
    assert client.post('/application-templates', json=body, headers=headers('consumer')).status_code == 403
    created = client.post('/application-templates', json=body, headers=headers('operator'))
    assert created.status_code == 201
    assert client.put('/application-templates/application', json=body, headers=headers('consumer')).status_code == 403
    assert client.put('/application-templates/application', json=body, headers=headers('author')).status_code == 200
    assert client.put('/application-templates/application', json=body, headers=headers('operator')).status_code == 200
    assert client.post('/application-templates/application/publish', headers=headers('outsider')).status_code == 403
    assert client.post('/application-templates/application/publish', headers=headers('author')).status_code == 200
    public = client.get('/application-templates/application', headers=headers('outsider')).json()['data']
    assert public['draft'] is None and len(public['versions']) == 2
    assert client.get('/application-templates/private-draft', headers=headers('outsider')).status_code == 404
    assert 'private-draft' not in {r['id'] for r in client.get('/application-templates', headers=headers('outsider')).json()['data']}


def test_all_parties_auto_confirm_and_delegation_is_immediately_effective(env):
    client, db, _ = env
    d = issue(env)
    initial = list(db.scalars(select(DelegationDecision).where(DelegationDecision.delegation_id == d['id'])))
    assert sorted((x.connector_id, x.kind, x.decision, x.decided_by) for x in initial) == sorted([
        ('provider', 'business', 'accepted', 'system'),
        ('consumer', 'business', 'accepted', 'system'),
        ('c1', 'service', 'accepted', 'system'),
        ('c2', 'service', 'accepted', 'system'),
        ('c3', 'service', 'accepted', 'system'),
    ])
    assert d['status'] == 'active'
    for cid, owner in [('c1', 'svc1'), ('c2', 'svc2'), ('c3', 'svc3')]:
        response = decide(client, d['id'], cid, owner)
        assert response.status_code == 200
        assert response.json()['data']['status'] == 'active'
    assert decide(client, d['id'], 'provider', 'provider').json()['data']['status'] == 'active'
    assert approved_services(db, db.get(Project, 'project')).id == d['id']
    assert decide(client, d['id'], 'c1', 'svc1', 'rejected').status_code == 409


def test_service_cannot_impersonate_business_or_view_another_inbox(env):
    client, _, _ = env
    d = issue(env)
    assert decide(client, d['id'], 'provider', 'svc1').status_code == 403
    assert decide(client, d['id'], 'other', 'outsider').status_code == 403
    assert client.get('/computation-delegations/inbox?connector_id=c1', headers=headers('outsider')).status_code == 403
    inbox = client.get('/computation-delegations/inbox?connector_id=c1', headers=headers('svc1'))
    assert inbox.status_code == 200
    row = inbox.json()['data'][0]
    assert [p['connector_id'] for p in row['scope']['participants']] == ['c1']
    assert all(v['connector_id'] == 'c1' for v in row['decisions'])
    assert client.get('/projects/project/delegations', headers=headers('svc1')).status_code == 404
    assert client.post('/projects/project/delegations', json=delegation_body(), headers=headers('outsider')).status_code == 404


def test_rejection_and_immutable_decisions(env):
    client, _, _ = env
    d = issue(env)
    assert decide(client, d['id'], 'consumer', 'consumer', 'rejected').status_code == 409
    # Service acceptance is a system authorization receipt; a service cannot
    # overwrite it with a late business rejection.
    response = decide(client, d['id'], 'c1', 'svc1', 'rejected')
    assert response.status_code == 409
    assert decide(client, d['id'], 'provider', 'provider').status_code == 200


def test_expired_delegation_cannot_be_accepted_or_used(env):
    client, db, _ = env
    d = issue(env)
    row = db.get(ComputationDelegation, d['id'])
    row.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
    db.commit()
    assert decide(client, d['id'], 'c1', 'svc1').status_code == 409
    row.status = 'active'
    db.commit()
    assert approved_services(db, db.get(Project, 'project')) is None
    body = delegation_body()
    body['expires_at'] = row.expires_at.isoformat()
    assert client.post('/projects/project/delegations', json=body, headers=headers('consumer')).status_code == 422


def test_business_can_revoke_service_cannot(env):
    client, db, _ = env
    d = activate(env)
    url = '/projects/project/delegations/'+d['id']+'/revoke'
    assert client.post(url, headers=headers('svc1')).status_code == 404
    assert client.post(url, headers=headers('provider')).json()['data']['status'] == 'revoked'
    assert approved_services(db, db.get(Project, 'project')) is None
    assert decide(client, d['id'], 'c1', 'svc1').status_code == 409


def test_identity_changes_invalidate_existing_delegations(env):
    client, db, _ = env
    d = activate(env)
    body = {'subject_id': 'institution:replacement', 'status': 'verified'}
    assert client.put('/execution-identities/c1', json=body, headers=headers('svc1')).status_code == 403
    assert client.put('/execution-identities/c1', json=body, headers=headers('operator')).status_code == 200
    assert db.get(ComputationDelegation, d['id']).status == 'identity-changed'
    assert approved_services(db, db.get(Project, 'project')) is None
    assert decide(client, d['id'], 'provider', 'provider').status_code == 409
    body['status'] = 'revoked'
    assert client.put('/execution-identities/c1', json=body, headers=headers('operator')).status_code == 200
    assert client.post('/projects/project/delegations', json=delegation_body(), headers=headers('consumer')).status_code == 409


def test_new_scope_supersedes_previous_delegation(env):
    client, db, _ = env
    first = issue(env)
    second = issue(env)
    assert second['version'] == first['version']+1
    assert db.get(ComputationDelegation, first['id']).status == 'superseded'
    assert decide(client, first['id'], 'c1', 'svc1').status_code == 409


@pytest.mark.parametrize('instances,participants', [
    ([{'version_id': 'version'}], None),
    ([{'id': ['invalid'], 'version_id': 'version'}], None),
    ([{'id': 'same', 'version_id': 'version'}, {'id': 'same', 'version_id': 'version'}], None),
    ([{'id': 'inference', 'version_id': ['invalid']}], None),
    (None, [{'connector_id': [], 'roles': ['compute1']}]),
    (None, [{'connector_id': 'c1', 'roles': [['compute1']]}]),
    (None, [{'connector_id': 'c1', 'roles': 'compute1'}]),
])
def test_invalid_delegation_structures_return_422(env, instances, participants):
    body = delegation_body()
    if instances is not None:
        body['instances'] = deepcopy(instances)
    if participants is not None:
        body['participants'] = deepcopy(participants)
    response = env[0].post('/projects/project/delegations', json=body, headers=headers('consumer'))
    assert response.status_code == 422, response.text


def test_project_seats_can_be_confirmed_before_application_selection(env):
    client, db, _ = env
    body = delegation_body()
    body.pop('instances')
    body['participants'] = [{'connector_id':'c'+str(n),'roles':[]} for n in range(1,4)]
    response=client.post('/projects/project/delegations',json=body,headers=headers('consumer'))
    assert response.status_code==201,response.text
    value=response.json()['data']
    assert value['scope']['mode']=='project-seats' and value['scope']['instances']==[]
    assert value['scope']['participants'][0]['roles']==['seat:0']
    assert decide(client,value['id'],'provider','provider').json()['data']['status']=='active'


@pytest.mark.parametrize('workflow', [[], 'invalid', {'applications': ['invalid']}, {'applications': [{'id': [], 'version_id': 'version'}]}, {'applications': [{'id': 'inference', 'version_id': []}]}])
def test_invalid_execution_plan_structures_return_422(env, workflow):
    response = env[0].post('/projects/project/execution-plan', json={'workflow': workflow}, headers=headers('consumer'))
    assert response.status_code == 422, response.text


def test_independent_logins_do_not_bypass_institution_separation(env):
    client, db, _ = env
    db.get(ExecutionIdentity, 'c2').subject_id = db.get(ExecutionIdentity, 'c1').subject_id
    db.commit()
    response = client.post('/projects/project/delegations', json=delegation_body(), headers=headers('consumer'))
    assert response.status_code == 422 and '独立主体' in response.text


def test_contract_extension_restricts_outsourcing_and_service_scope(env):
    client, db, _ = env
    contract = db.get(DigitalContract, 'contract')
    document = deepcopy(contract.document)
    document['contractInfo']['expansionItem']['computationOutsourcing']['allowedConnectors'] = ['c1']
    contract.document = document
    db.commit()
    assert client.post('/projects/project/delegations', json=delegation_body(), headers=headers('consumer')).status_code == 403
    document = deepcopy(contract.document)
    document['contractInfo']['expansionItem']['computationOutsourcing']['allowed'] = False
    contract.document = document
    db.commit()
    assert client.post('/projects/project/delegations', json=delegation_body(), headers=headers('consumer')).status_code == 403


def test_decision_reply_loss_can_retry_active_acceptance_without_reauthorizing_revocation(env):
    client, _, _ = env
    d=activate(env)
    response=decide(client,d['id'],'c3','svc3')
    assert response.status_code==200 and response.json()['data']['status']=='active'
    assert client.post('/projects/project/delegations/'+d['id']+'/revoke',headers=headers('consumer')).status_code==200
    assert decide(client,d['id'],'c3','svc3').status_code==409


def test_computation_directory_exposes_only_verified_minimal_identities(env):
    from app.models import ConnectorCapability
    client,db,_=env
    for cid in ['c1','c2']:
        db.add(ConnectorCapability(connector_id=cid,capability_code='mpc',status='verified',evidence={'network':{'execution_node_ref':'domain-'+cid,'connector_endpoint':'private-endpoint'}}))
    db.get(ExecutionIdentity,'c2').status='revoked';db.commit()
    response=client.get('/computation-services',headers=headers('consumer'))
    assert response.status_code==200
    rows=response.json()['data']
    assert [x['id'] for x in rows]==['c1']
    assert set(rows[0])=={'id','name','org_name','status','subject_id'}
    assert 'private-endpoint' not in response.text and 'csr_pem' not in response.text


def test_readiness_reuses_roles_and_rechecks_on_application_change(env):
    client, db, _ = env
    body = {'workflow': {'applications': [{'id': 'inference', 'version_id': 'version'}]}}
    def check():
        client.raise_server_exceptions = True
        response = client.post('/projects/project/delegation-readiness', json=body)
        assert response.status_code == 200, response.text
        return response.json()['data']
    assert not check()['ready']
    d = activate(env)
    contract=db.get(DigitalContract,'contract')
    contract.document={**contract.document,'contractPolicies':[{**p,'policyType':'permission','actions':['process']} for p in contract.document['contractPolicies']]}
    db.commit()
    # Authentication and authorization still apply before checking requirements.
    assert client.post('/projects/project/delegation-readiness', json=body, headers=headers('outsider')).status_code == 404
    result = check()
    assert result['roles']['inference']['compute3'] == 'c3'
    assert not result['ready'] and '能力' in result['issues'][0]['message']
    from app.models import ConnectorCapability
    for cid in ['provider', 'c1', 'c2', 'c3']:
        db.add(ConnectorCapability(connector_id=cid, capability_code='mpc', capability_version='1', status='verified', adapter_type='kuscia', implementation_ref=cid))
    db.commit()
    assert check()['ready']
    body['workflow']['applications'][0]['parameters'] = {'batch': 128}
    assert check()['ready']
    delegation = db.get(ComputationDelegation, d['id'])
    delegation.scope = {**delegation.scope, 'participants': delegation.scope['participants'][:1]}
    db.commit()
    assert not check()['ready'] and '更多计算席位' in check()['issues'][0]['message']


def test_publishing_names_is_strict_but_existing_versions_stay_readable(env):
    client, db, definition = env
    legacy = db.get(ApplicationTemplateVersion, 'version')
    original_hash = legacy.definition_hash
    definition['outputs'][0].pop('title')
    client.put('/application-templates/application', json={'name': 'Inference', 'draft': definition}, headers=headers('author'))
    response = client.post('/application-templates/application/publish', headers=headers('author'))
    assert response.status_code == 422 and '可读名称' in response.text
    assert client.get('/application-templates/versions/version').status_code == 200
    assert legacy.definition_hash == original_hash


def test_submission_snapshots_delegation_scope_and_expiry(env, monkeypatch):
    from app.services import project as projects
    client, db, _ = env
    d = issue(env)
    # Exercise submission snapshotting independently of resource grant fixtures.
    monkeypatch.setattr(projects, 'validate_workflow', lambda *args: None)
    workflow = {'applications': [{'id': 'inference', 'version_id': 'version', 'parameters': {}, 'roles': {}, 'inputs': {}}], 'nodes': [], 'edges': []}
    version = projects.submit(db, db.get(Project, 'project'), 'consumer', workflow)
    snapshot = version.workflow['delegation_snapshot']
    assert snapshot['id'] == d['id']
    assert snapshot['scope']['participants'] == [{'connector_id': 'c'+str(n), 'roles': ['compute'+str(n)]} for n in range(1, 4)]
    assert snapshot['scope_hash'] == d['scope_hash']
    assert snapshot['expires_at']
    original_hash = version.workflow_hash
    issue(env)
    db.refresh(version)
    assert version.workflow['delegation_snapshot']['id'] == d['id']
    assert version.workflow_hash == original_hash


@pytest.mark.parametrize('detached', [False, True])
def test_run_revalidation_ignores_submission_audit_snapshot_only(env, monkeypatch, detached):
    from app.services import project as projects
    from app.services import application_template as templates
    client, db, _ = env
    issue(env)
    workflow = {'applications': [{'id': 'inference', 'version_id': 'version', 'parameters': {}, 'roles': {}, 'inputs': {}}], 'nodes': [], 'edges': []}
    if detached:
        expanded = templates.expand(db, db.get(Project, 'project'), workflow)
        workflow = {'applications': [], 'detached_applications': workflow['applications'], 'nodes': expanded['nodes'], 'edges': expanded['edges']}
        for node in workflow['nodes']:
            node['detached'] = True
    monkeypatch.setattr(projects, 'validate_workflow', lambda *args: None)
    project = db.get(Project, 'project')
    version = projects.submit(db, project, 'consumer', workflow)
    assert version.workflow['delegation_snapshot']['id']
    project.status = 'approved'
    db.commit()
    monkeypatch.setattr(projects, 'connectivity_status', lambda *args: {'connected': True})
    class ReachedExecutionValidation(Exception):
        pass
    def validated(*args):
        raise ReachedExecutionValidation()
    monkeypatch.setattr(projects, 'validate_workflow', validated)
    # Stop before creating any execution, after application binding comparison.
    with pytest.raises(ReachedExecutionValidation):
        projects.run(db, project, 'consumer')
    expand = templates.expand
    def changed(*args):
        value = expand(*args)
        value['nodes'][0]['parameters']['size'] = 999
        return value
    monkeypatch.setattr(templates, 'expand', changed)
    with pytest.raises(projects.ProjectError, match='应用绑定发生变化'):
        projects.run(db, project, 'consumer')
