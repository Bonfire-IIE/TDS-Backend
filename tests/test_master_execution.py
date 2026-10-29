import copy
import pytest
from app.integrations.kuscia import KusciaError
from app.services import master_execution as svc, execution_dispatch

@pytest.fixture
def rig(monkeypatch):
    saved = {}; calls = []; jobs = {}; attempts = []
    class Master:
        def domain_online(self, domain): return True
        def query_route(self,*args): return {}
        def route_status(self,*args): return "Succeeded"
        def close(self): pass
        def query_job(self, job_id):
            if job_id not in jobs: raise KusciaError('job not found')
            return jobs[job_id]
        def create_job(self, job):
            attempts.append(job['job_id'])
            jobs[job['job_id']]={'status':{'state':'Succeeded'}}
            if len(attempts)==1: raise KusciaError('reply lost after accepted')
    monkeypatch.setattr(svc,'get_kuscia_client',Master)
    monkeypatch.setattr(svc,'_snapshot',lambda run: copy.deepcopy(saved))
    def save(run,state,status=None,error=None):
        saved.clear();saved.update(copy.deepcopy(state));calls.append(status)
    monkeypatch.setattr(svc,'_save',save)
    actions=[]
    def post(endpoint,run,connector,action,body,timeout=None):
        actions.append(action)
        assert body['execution_request']['scheduling_mode']=='master-lite'
        return {'run_id':run,'connector_id':connector,'domain_id':connector+'-domain','manifests':[]}
    monkeypatch.setattr(execution_dispatch,'_post',post)
    monkeypatch.setattr(svc,'_compile_job',lambda req,m,j,d:({'job_id':j},{},[]))
    request={role+'_connector_id':role for role in ('provider','consumer')}
    for role in ('provider','consumer'):
        request[role+'_execution_node_ref']=role+'-domain'
        request[role+'_connector_endpoint']='http://'+role
        request[role+'_gateway_endpoint']='https://'+role
    return request,saved,actions,attempts,calls,Master

def test_master_recovers_lost_submission_without_second_job_or_edge_scheduling(rig):
    request,state,actions,attempts,statuses,_=rig
    with pytest.raises(KusciaError):svc.dispatch_master_run('run-1',request)
    assert state['phase']=='submission-intent'
    result=svc.dispatch_master_run('run-1',request)
    assert result['status']=='succeeded'
    assert len(attempts)==1
    assert actions==['prepare','prepare']
    assert statuses==['accepted','accepted','accepted','succeeded']

def test_uncertain_master_query_does_not_submit(rig,monkeypatch):
    request,state,actions,attempts,statuses,Master=rig
    monkeypatch.setattr(Master,'query_job',lambda *args:(_ for _ in ()).throw(KusciaError('timeout')))
    with pytest.raises(KusciaError):svc.dispatch_master_run('run-2',request)
    assert attempts==[]
    assert statuses==['accepted','accepted','accepted']

def test_invalid_compilation_is_reported_instead_of_retrying_forever(rig,monkeypatch):
    request,state,actions,attempts,statuses,_=rig
    monkeypatch.setattr(svc,'_compile_job',lambda *args:(_ for _ in ()).throw(ValueError('invalid declared output')))
    result=svc.dispatch_master_run('invalid-plan',request)
    assert result['status']=='failed' and 'invalid declared output' in result['error']
    assert state['phase']=='compilation-failed' and attempts==[]
    assert statuses[-1]=='failed'

@pytest.mark.parametrize('retryable', [False, True])
def test_preparation_rejection_is_terminal_but_transport_error_retries(rig, monkeypatch, retryable):
    request, state, actions, attempts, statuses, _ = rig
    def reject(*args, **kwargs):
        raise execution_dispatch.DispatchError('provider', 'HTTP 422: invalid_dr_resource_version', retryable=retryable)
    monkeypatch.setattr(execution_dispatch, '_post', reject)
    if retryable:
        with pytest.raises(execution_dispatch.DispatchError):
            svc.dispatch_master_run('rejected', request)
        assert statuses == ['accepted']
    else:
        result = svc.dispatch_master_run('rejected', request)
        assert result['status'] == 'failed'
        assert statuses == ['accepted', 'failed']
        assert state['phase'] == 'preparation-failed'
    assert attempts == []


def test_cancel_before_submission_never_creates_engine_job(rig):
    request,state,actions,attempts,statuses,_=rig
    state['cancel_requested']=True
    result=svc.dispatch_master_run('cancel-before-submit',request)
    assert result['status']=='cancelled'
    assert actions==[] and attempts==[] and statuses==['cancelled']


def test_cancel_persisted_submission_intent_with_no_job_does_not_stall(rig):
    request,state,actions,attempts,statuses,_=rig
    state.update(cancel_requested=True,job_id='never-created',job={'job_id':'never-created'})
    result=svc.dispatch_master_run('cancel-intent',request)
    assert result['status']=='cancelled'
    assert actions==[] and attempts==[] and statuses==['cancelled']


def test_reconciliation_persists_real_task_progress(rig, monkeypatch):
    request, state, _, _, _, Master = rig
    request['workflow'] = {'nodes': [{'id': 'first'}, {'id': 'second'}], 'edges': []}
    state.update(job_id='job', job={'job_id': 'job'}, outputs={})
    monkeypatch.setattr(Master, 'query_job', lambda *args: {
        'job_id': 'job', 'status': {'state': 'Running', 'tasks': [
            {'task_id': 'job-first', 'state': 'Succeeded'},
            {'task_id': 'job-second', 'state': 'Running'},
        ]}})
    result = svc.dispatch_master_run('run-progress', request)
    assert result['status'] == 'running'
    assert state['task_progress']['completed'] == 1
    assert state['task_progress']['running'] == 1
    assert state['task_progress']['total'] == 2
