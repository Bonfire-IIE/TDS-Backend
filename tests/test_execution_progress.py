from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.integrations.kuscia import KusciaError
from app.models import Project, ProjectRun
from app.services import master_execution
from app.services.execution_progress import task_progress


def request():
    return {'scheduling_mode': 'master-lite', 'workflow': {'nodes': [
        {'id': 'share-model', 'alias': '模型分享'},
        {'id': 'share-query', 'alias': '图片分享'},
        {'id': 'infer', 'alias': '安全推理'},
        {'id': 'recover', 'alias': '结果恢复'},
    ]}}


def job(states):
    return {'job_id': 'job', 'status': {'state': 'Failed', 'tasks': [
        {'task_id': 'job-' + node['id'], 'state': state}
        for node, state in zip(request()['workflow']['nodes'], states)
    ]}}


def test_counts_tasks_once_not_parties_and_ignores_unrelated_reports():
    value = job(['Succeeded', 'Succeeded', 'Succeeded', 'Failed'])
    value['status']['tasks'][0]['parties'] = [{'state': 'Succeeded'}] * 4
    value['status']['tasks'] += [value['status']['tasks'][0], {'task_id': 'unrelated', 'state': 'Succeeded'}]
    progress = task_progress(request(), value)
    assert (progress['completed'], progress['total'], progress['failed']) == (3, 4, 1)
    assert progress['tasks'][0]['name'] == '模型分享'
    assert len(progress['tasks']) == 4


def test_running_and_pending_are_not_completed():
    progress = task_progress(request(), job(['Succeeded', 'Running', 'Pending', 'Pending']))
    assert (progress['completed'], progress['running'], progress['pending']) == (1, 1, 2)


def test_no_engine_job_means_not_yet_started():
    progress = task_progress(request())
    assert not progress['observed']
    assert (progress['completed'], progress['pending'], progress['total']) == (0, 4, 4)


def test_missing_engine_states_are_unknown_even_if_job_succeeded():
    value = job(['Succeeded'])
    value['status']['state'] = 'Succeeded'
    progress = task_progress(request(), value)
    assert (progress['completed'], progress['unknown'], progress['total']) == (1, 3, 4)


def test_normalizes_legacy_terminal_names_and_preserves_unknown():
    progress = task_progress(request(), job(['Finished', 'Canceled', 'ApprovalReject', 'Suspended']))
    assert (progress['completed'], progress['cancelled'], progress['failed'], progress['unknown']) == (1, 1, 1, 1)


def test_uses_compiled_task_ids_for_long_node_names():
    from app.integrations.privacy_compute.compiler import _engine_task_id
    req = {'workflow': {'nodes': [{'id': 'node-' + 'x' * 80, 'alias': '长任务名'}]}}
    task_id = _engine_task_id('job', req['workflow']['nodes'][0]['id'])
    progress = task_progress(req, {'job_id': 'job', 'status': {'tasks': [{'task_id': task_id, 'state': 'Succeeded'}]}})
    assert progress['completed'] == 1


@pytest.fixture
def persisted(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(master_execution, 'SessionLocal', sessions)
    original = {
        'execution_request': request(),
        'master_execution': {'job_id': 'job', 'phase': 'submitted'},
        'artifact_lifecycle': {'state': 'cleaned'},
        'result_guidance': {'outputs': []},
        'usage_record_ids': ['reserved-record'],
    }
    with sessions() as db:
        db.add(Project(id='project', name='Project', contract_id='contract', initiator_connector_id='a',
                       created_by='a', status='failed'))
        db.add(ProjectRun(id='run', project_id='project', workflow_version_id='version', kuscia_job_id='job',
                          status='failed', job_snapshot=original, failure_info={'message': 'original failure'}, created_by='a'))
        db.commit()
    yield sessions, original
    engine.dispose()


def test_refresh_historical_failed_run_only_merges_progress(persisted, monkeypatch):
    sessions, original = persisted
    closed = []

    class Engine:
        def query_job(self, job_id):
            assert job_id == 'job'
            # Simulate concurrent cleanup metadata saved while the engine call is in flight.
            with sessions() as db:
                row = db.get(ProjectRun, 'run')
                row.job_snapshot = {**row.job_snapshot, 'concurrent_marker': True}
                db.commit()
            return job(['Succeeded', 'Succeeded', 'Succeeded', 'Failed'])

        def close(self):
            closed.append(True)

    monkeypatch.setattr(master_execution, 'get_kuscia_client', Engine)
    master_execution.refresh_task_progress('run')
    with sessions() as db:
        row = db.get(ProjectRun, 'run')
        snapshot = deepcopy(row.job_snapshot)
        progress = snapshot['master_execution'].pop('task_progress')
        assert progress['completed'] == 3
        assert snapshot.pop('concurrent_marker') is True
        assert snapshot == original
        assert row.status == 'failed' and row.failure_info == {'message': 'original failure'}
        assert db.get(Project, 'project').status == 'failed'
    assert closed == [True]


def test_unavailable_engine_keeps_last_observed_snapshot(persisted, monkeypatch):
    sessions, original = persisted
    class Engine:
        def query_job(self, _):
            raise KusciaError('engine unavailable')
        def close(self):
            pass
    monkeypatch.setattr(master_execution, 'get_kuscia_client', Engine)
    master_execution.refresh_task_progress('run')
    with sessions() as db:
        assert db.get(ProjectRun, 'run').job_snapshot == original
