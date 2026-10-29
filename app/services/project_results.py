"""Authenticated connector-local project result views."""
from pathlib import PurePosixPath
from app.models import Connector, Project, ProjectRun
from app.models.application_template import ApplicationTemplateVersion
from app.services.project import ProjectError


def owned_connector(db, connector_id, username):
    connector = db.get(Connector, connector_id)
    if not connector or connector.deleted_at is not None or connector.status != 'active' or connector.created_by != username:
        raise ProjectError('请登录此连接器所属账号', 403)
    return connector


def local_nodes(run, connector_id):
    snap = run.job_snapshot or {}
    workflow = (snap.get('execution_snapshot') or {}).get('workflow') or (snap.get('execution_request') or {}).get('workflow') or {}
    return [n for n in workflow.get('nodes', []) if any((p.get('connector_id') or p.get('domain_id')) == connector_id for p in n.get('parties', []))]


def local_view(db, run, connector_id):
    nodes = local_nodes(run, connector_id)
    if not nodes: raise ProjectError('此连接器未参与该执行批次', 403)
    project = db.get(Project, run.project_id)
    snap = run.job_snapshot or {}
    progress = (snap.get('master_execution') or {}).get('task_progress') or {}
    progress_by_id = {t['node_id']: t for t in progress.get('tasks', [])}
    tasks = []
    for node in nodes:
        version = db.get(ApplicationTemplateVersion, node['template_version']) if node.get('template_version') else None
        definition = version.definition if version else {}
        template_task = next((t for t in definition.get('tasks', []) if t['id'] == node.get('template_task')), {})
        image = (definition.get('appimage_snapshots') or {}).get(node.get('app_image'), {})
        alias = node.get('alias')
        name = alias if alias and alias not in {node['id'], node.get('template_task')} else template_task.get('alias') or image.get('display_name') or '计算任务'
        observed = progress_by_id.get(node['id'], {})
        tasks.append({'node_id':node['id'], 'name':name, 'task_id':observed.get('task_id'), 'status':observed.get('state', 'unknown')})
    outputs = []
    for output in (snap.get('result_guidance') or {}).get('outputs', []):
        path = str(output.get('relative_uri') or '')
        parsed = PurePosixPath(path)
        if output.get('connector_id') != connector_id or not path or parsed.is_absolute() or '..' in parsed.parts: continue
        # Only explicit final output files from the authoritative execution snapshot.
        if not path.startswith('projects/' + run.project_id + '/' + run.id + '/'): continue
        task = next((t for t in tasks if t['node_id'] == output.get('node')), None)
        outputs.append({'path':path, 'name':parsed.name, 'task_name':task['name'] if task else '结果输出', 'port':output.get('port')})
    return {'project_id':run.project_id, 'project_name':project.name if project else '计算项目', 'run_id':run.id,
            'job_id':run.kuscia_job_id, 'status':run.status, 'created_at':run.created_at.isoformat(),
            'tasks':tasks, 'outputs':outputs}
