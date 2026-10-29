"""Terminal-task confirmation and durable cleanup reconciliation boundaries."""
from copy import deepcopy
import hashlib
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.db import Base
from app.models import Project, ProjectRun
from app.services import master_execution as svc, execution_dispatch

@pytest.fixture
def rig(monkeypatch):
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine);monkeypatch.setattr(svc,'SessionLocal',sessions)
    request={'artifact_plan':[], 'participants':[{'connector_id':c,'connector_endpoint':'http://'+c} for c in ['a','b']]}
    with sessions() as db:
        db.add(Project(id='project',name='Project',contract_id='contract',initiator_connector_id='a',created_by='a'))
        db.add(ProjectRun(id='run',project_id='project',workflow_version_id='workflow',kuscia_job_id='job',status='succeeded',job_snapshot={'master_execution':{'job_id':'job'},'execution_request':request},created_by='a'));db.commit()
    calls=[];tasks=[{'state':'Succeeded'}]
    class Engine:
        def query_job(self,_):return {'status':{'tasks':deepcopy(tasks)}}
        def job_quiescence(self,job_id,task_ids,reference_scope=None):
            stopped=all(t['state']=='Succeeded' for t in tasks)
            return {'job_id':job_id,'terminal':stopped,'completed':stopped,'created_task_ids':task_ids,'never_created_task_ids':[],**reference_proof(reference_scope)}
        def close(self):pass
    monkeypatch.setattr(svc,'get_kuscia_client',Engine)
    def post(endpoint,run,cid,phase,body,timeout):
        calls.append((cid,body['phase']))
        if body['phase']=='scope':return {'run_id':run,'connector_id':cid,'reference_scope':['input-'+cid]}
        if body['phase']=='cleanup':assert body['tasks_stopped'] is True
        return {'connector_id':cid,'state':'cleaned' if body['phase']=='cleanup' else 'verified'}
    monkeypatch.setattr(execution_dispatch,'_post',post)
    yield sessions,request,calls,tasks,post
    engine.dispose()

def lifecycle(sessions):
    with sessions() as db:return deepcopy(db.get(ProjectRun,'run').job_snapshot.get('artifact_lifecycle'))

def test_success_verifies_before_cleanup_and_reconcile_is_idempotent(rig):
    sessions,request,calls,_,_=rig
    svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','verify'),('b','verify'),('a','cleanup'),('b','cleanup')]
    assert lifecycle(sessions)['state']=='cleaned'
    svc.reconcile_artifacts('run',request)
    assert len(calls)==6

def test_terminal_run_does_not_delete_with_unstopped_task(rig):
    sessions,request,calls,tasks,_=rig;tasks.append({'state':'Running'})
    svc.reconcile_artifacts('run',request)
    assert all(c[1]=='scope' for c in calls) and lifecycle(sessions)['state']=='pending-confirmation'

def test_verify_failure_preserves_all_outputs_and_can_resume(rig,monkeypatch):
    sessions,request,calls,_,post=rig
    def unavailable(*args):
        if args[2]=='b' and args[4]['phase']!='scope':raise execution_dispatch.DispatchError('b','unreachable',retryable=True)
        return post(*args)
    monkeypatch.setattr(execution_dispatch,'_post',unavailable)
    svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','verify')]
    assert lifecycle(sessions)['state']=='pending-confirmation'
    monkeypatch.setattr(execution_dispatch,'_post',post);svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','verify'),('b','verify'),('a','cleanup'),('b','cleanup')]
    assert lifecycle(sessions)['state']=='cleaned'

def test_failure_cleanup_retries_only_unconfirmed_domain(rig,monkeypatch):
    sessions,request,calls,_,post=rig
    with sessions() as db:db.get(ProjectRun,'run').status='failed';db.commit()
    def unavailable(*args):
        if args[2]=='b' and args[4]['phase']!='scope':raise execution_dispatch.DispatchError('b','unreachable',retryable=True)
        return post(*args)
    monkeypatch.setattr(execution_dispatch,'_post',unavailable);svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','cleanup')]
    monkeypatch.setattr(execution_dispatch,'_post',post);svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','cleanup'),('b','cleanup')]
    assert lifecycle(sessions)['state']=='cleaned'

def test_unprepared_domain_404_is_safe_only_before_job_submission(rig,monkeypatch):
    sessions,request,_,_,_=rig
    def missing(*args):raise execution_dispatch.DispatchError(args[2],'not prepared',status_code=404)
    monkeypatch.setattr(execution_dispatch,'_post',missing)
    with sessions() as db:db.get(ProjectRun,'run').status='failed';db.commit()
    svc.reconcile_artifacts('run',request)
    assert lifecycle(sessions)['state']=='pending-confirmation'
    with sessions() as db:db.get(ProjectRun,'run').job_snapshot={'master_execution':{},'execution_request':request};db.commit()
    svc.reconcile_artifacts('run',request)
    assert lifecycle(sessions)['state']=='cleaned'


def test_authoritative_never_created_proof_allows_failed_downstream_cleanup(rig,monkeypatch):
    sessions,request,calls,tasks,_=rig
    request['workflow']={'nodes':[{'id':'downstream'}]}
    tasks[:]=[{'state':'Pending'}]
    class Engine:
        def job_quiescence(self,job_id,task_ids,reference_scope=None):return {'job_id':job_id,'terminal':True,'completed':True,'created_task_ids':[],'never_created_task_ids':task_ids,**reference_proof(reference_scope)}
        def close(self):pass
    monkeypatch.setattr(svc,'get_kuscia_client',Engine)
    with sessions() as db:db.get(ProjectRun,'run').status='failed';db.commit()
    svc.reconcile_artifacts('run',request)
    assert [c for c in calls if c[1]!='scope']==[('a','cleanup'),('b','cleanup')]
    assert lifecycle(sessions)['state']=='cleaned'
    assert lifecycle(sessions)['stop_proof']['never_created_task_ids']==['job-downstream']


def test_incomplete_master_stop_proof_cannot_delete_any_domain(rig,monkeypatch):
    sessions,request,calls,_,_=rig
    request['workflow']={'nodes':[{'id':'upstream'},{'id':'downstream'}]}
    class Engine:
        def job_quiescence(self,job_id,task_ids,reference_scope=None):return {'job_id':job_id,'terminal':True,'completed':True,'created_task_ids':task_ids[:1],'never_created_task_ids':[],**reference_proof(reference_scope)}
        def close(self):pass
    monkeypatch.setattr(svc,'get_kuscia_client',Engine)
    svc.reconcile_artifacts('run',request)
    assert all(c[1]=='scope' for c in calls) and lifecycle(sessions)['state']=='pending-confirmation'


def reference_proof(scope):
    scope=sorted(scope or [])
    return {'references_clear':True,'reference_scope':scope,'reference_hash':hashlib.sha256(json.dumps(scope,separators=(',',':')).encode()).hexdigest()}


def test_scope_failure_blocks_master_and_all_cleanup(rig,monkeypatch):
    sessions,request,calls,_,post=rig
    def unavailable(*args):
        if args[2]=='b' and args[4]['phase']=='scope':
            raise execution_dispatch.DispatchError('b','unreachable',retryable=True)
        return post(*args)
    class Engine:
        def job_quiescence(self,*args):raise AssertionError('Master must not receive incomplete reference scope')
        def close(self):pass
    monkeypatch.setattr(svc,'get_kuscia_client',Engine)
    monkeypatch.setattr(execution_dispatch,'_post',unavailable)
    svc.reconcile_artifacts('run',request)
    assert calls==[('a','scope')]
    assert lifecycle(sessions)['state']=='pending-confirmation'
    assert 'scope' in lifecycle(sessions)['errors']

def test_legacy_privacy_run_uses_same_cleanup_and_durable_receipts(rig):
    from app.models.privacy_compute import PrivacyComputeRun
    sessions,request,calls,_,_=rig
    with sessions() as db:
        db.add(PrivacyComputeRun(id='legacy',project_id='legacy-project',created_by='a',status='succeeded',evidence={'master_execution':{'job_id':'job'},'execution_request':request}))
        db.commit()
    svc.reconcile_artifacts('legacy',request)
    with sessions() as db:
        assert db.get(PrivacyComputeRun,'legacy').evidence['artifact_lifecycle']['state']=='cleaned'
    before=len(calls);svc.reconcile_artifacts('legacy',request);assert len(calls)==before
