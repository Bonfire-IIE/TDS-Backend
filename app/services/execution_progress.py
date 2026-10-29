"""Task counts come from the engine, never from the overall run outcome."""
from datetime import datetime, timezone

from app.integrations.privacy_compute.compiler import _engine_task_id


def task_progress(request, job=None):
    nodes = (request.get('workflow') or {}).get('nodes') or []
    job_id = (job or {}).get('job_id')
    configs = (job or {}).get('tasks') or []
    if nodes:
        expected = [{'node_id': n['id'], 'task_id': _engine_task_id(job_id, n['id']) if job_id else None,
                     'name': n.get('alias') or n['id']} for n in nodes]
    else:
        expected = [{'node_id': t['task_id'], 'task_id': t['task_id'],
                     'name': t.get('alias') or t['task_id']} for t in configs]
    reported = {t['task_id']: t for t in ((job or {}).get('status') or {}).get('tasks') or []
                if t.get('task_id')}
    counts = dict(completed=0, running=0, failed=0, cancelled=0, pending=0, unknown=0)
    tasks = []
    for item in expected:
        actual = reported.get(item['task_id'], {})
        state = str(actual.get('state') or ('Pending' if job is None else 'Unknown')).lower()
        state = {'finished': 'succeeded', 'canceled': 'cancelled', 'approvalreject': 'failed'}.get(state, state)
        if state not in {'succeeded', 'running', 'failed', 'cancelled', 'pending'}:
            state = 'unknown'
        counts['completed' if state == 'succeeded' else state] += 1
        tasks.append({**item, 'state': state,
                      'message': str(actual.get('err_msg') or '')[:2000] or None,
                      'start_time': actual.get('start_time') or None,
                      'end_time': actual.get('end_time') or None})
    return {'total': len(tasks), **counts, 'tasks': tasks, 'observed': job is not None,
            'updated_at': datetime.now(timezone.utc).isoformat()}
