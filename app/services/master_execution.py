"""Center control plane: prepare inputs at Lite, submit/query only Kuscia Master.

The DB snapshot is a durable submission intent. A deterministic job ID and
query-before-create recover lost replies without creating a second job.
"""
from __future__ import annotations
import hashlib
import json
from sqlalchemy import select
from app.core.db import SessionLocal
from app.integrations.kuscia import get_kuscia_client, KusciaError
from app.integrations.privacy_compute.compiler import _compile_job, _validate_peer_bundle, _engine_task_id
from app.models.privacy_compute import PrivacyComputeRun, PrivacyComputeProject
from app.models.project import ProjectRun, Project
from app.services.execution_compat import normalize_execution_request
from app.services.execution_progress import task_progress

TERMINAL = {'succeeded', 'failed', 'cancelled'}

def _canonical(value):
    """Ignore protobuf's empty/default fields, preserving non-default behavior."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()
                if v not in (None, '', [], {}) and not (k == 'image_pull_policy' and v == 'IfNotPresent')}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value

def _load(db, run_id):
    row = db.get(PrivacyComputeRun, run_id)
    if row:
        return row, 'evidence', 'external_run_ref', PrivacyComputeProject
    return db.get(ProjectRun, run_id), 'job_snapshot', 'kuscia_job_id', Project

def _snapshot(run_id):
    with SessionLocal() as db:
        row, attr, _, _ = _load(db, run_id)
        if row is None:
            raise ValueError('execution run not found')
        record=getattr(row,attr) or {}
        state=dict(record.get('master_execution') or {})
        if record.get('cancel_requested'):state['cancel_requested']=True
        return state

def _save(run_id, snapshot, status=None, error=None):
    with SessionLocal() as db:
        row, attr, ref, project_model = _load(db, run_id)
        if row is None or row.status in TERMINAL:
            return
        setattr(row, attr, {**(getattr(row, attr) or {}), 'master_execution': snapshot})
        if snapshot.get('job_id'):
            setattr(row, ref, snapshot['job_id'])
        previous = row.status
        if status:
            row.status = status
        if isinstance(row, PrivacyComputeRun):
            row.error = error
            if snapshot.get('result') is not None:
                row.result = snapshot['result']
        else:
            row.failure_info = {'message': error} if error else None
            if snapshot.get('result') is not None:
                row.job_snapshot = {**row.job_snapshot, 'result': snapshot['result']}
            if status in {'failed', 'cancelled'} and previous not in TERMINAL:
                from app.services import usage
                ids = row.job_snapshot.get('usage_record_ids') or []
                usage.compensate_many(db, ids, error or status)
        project = db.get(project_model, row.project_id)
        if project and status:
            latest = db.scalar(select(type(row)).where(type(row).project_id == row.project_id)
                               .order_by(type(row).created_at.desc(), type(row).id.desc()).limit(1))
            if latest and latest.id == row.id:
                project.status = 'completed' if status == 'succeeded' else 'failed' if status in TERMINAL else 'running'
        db.commit()

def dispatch_master_run(run_id, request):
    from app.services.execution_dispatch import _post, _endpoint, DispatchError
    request = normalize_execution_request(request, scheduling_mode='master-lite')
    state = _snapshot(run_id)
    if 'task_progress' not in state:
        state['task_progress'] = task_progress(request)
    client = get_kuscia_client()
    try:
        if state.get('cancel_requested'):
            if not state.get('job_id'):
                _save(run_id,state,'cancelled');return {'status':'cancelled'}
            try:existing=client.query_job(state['job_id'])
            except KusciaError as exc:
                if not any(v in str(exc).lower() for v in ('not found','not exist')):raise
                _save(run_id,state,'cancelled');return {'status':'cancelled'}
            if str((existing.get('status') or {}).get('state','')).lower() not in {'succeeded','finished','failed','cancelled','canceled','approvalreject'}:
                client.cancel_job(state['job_id'])
        if not state.get('job'):
            from urllib.parse import urlsplit
            # Routes are Master-owned topology, distributed to Lite by Kuscia.
            # No edge Domain creation, peer certificates or autonomous scheduler.
            participants=request.get('participants') or [{
                'connector_id':request.get(role+'_connector_id'),
                'execution_node_ref':request.get(role+'_execution_node_ref'),
                'gateway_endpoint':request.get(role+'_gateway_endpoint'),
                'connector_endpoint':request.get(role+'_connector_endpoint'),
            } for role in ('provider','consumer')]
            participant_map={p['connector_id']:p for p in participants}
            required_pairs=set()
            for node in request.get('workflow',{}).get('nodes',[]):
                ids=[p.get('connector_id') or p.get('domain_id') for p in node.get('parties',[])]
                required_pairs.update((a,b) for a in ids for b in ids if a!=b)
            if not required_pairs:
                required_pairs={(a,b) for a in participant_map for b in participant_map if a!=b}
            for src,dst in sorted(required_pairs):
                source=participant_map[src]['execution_node_ref'];target=participant_map[dst]['execution_node_ref']
                gateway=urlsplit(_endpoint(participant_map[dst].get('gateway_endpoint'),dst))
                if client.query_route(source,target) is None:
                    client.create_cluster_route(source,target,gateway.hostname,gateway.port or (443 if gateway.scheme=='https' else 80),gateway.scheme=='https')
                if client.route_status(source,target)!='Succeeded':raise KusciaError('Master domain route is not ready')
            domains,manifests={},{}
            for participant in participants:
                connector=participant['connector_id'];domain=participant['execution_node_ref']
                if not connector or not domain or not client.domain_online(domain):
                    raise KusciaError('participating Lite is not registered/online at center Master')
                domains[connector]=domain
                state.update({'phase':'preparing-inputs','preparing_connector':connector})
                _save(run_id,state,'accepted')
                prepared=_post(_endpoint(participant.get('connector_endpoint'),connector),run_id,
                               connector,'prepare',{'connector_id':connector,'execution_request':request},35)
                manifests.update(_validate_peer_bundle(prepared,request,connector,domain,run_id))
            job_id = 'kuscia-' + hashlib.sha256(run_id.encode()).hexdigest()[:28]
            job, outputs, images = _compile_job(request, manifests, job_id, domains)
            # Master distributes AppImages to all participating Lite nodes.
            for app in images:
                templates = []
                for item in app['deploy_templates']:
                    spec = item.get('spec') or item
                    templates.append({'name': item.get('name'), 'role': item.get('role'),
                                      'replicas': item.get('replicas', 1),
                                      'restart_policy': spec.get('restart_policy', 'Never'),
                                      'containers': spec.get('containers') or []})
                try:
                    existing = client.query_appimage(app['name'])
                except KusciaError as exc:
                    if not any(v in str(exc).lower() for v in ('not found', 'not exist')):
                        raise
                    existing = None
                if existing:
                    # A running application's definition must not be replaced silently.
                    expected = {'name': app['image_name'], 'tag': app['image_tag']}
                    if (_canonical(existing.get('image')) != _canonical(expected)
                            or _canonical(existing.get('deploy_templates')) != _canonical(templates)
                            or _canonical(existing.get('config_templates') or {}) != _canonical(app.get('config_templates') or {})):
                        raise ValueError('Master AppImage conflicts with requested definition')
                else:
                    client.create_appimage(app['name'], app['image_name'], app['image_tag'],
                                           templates, app.get('config_templates'))
            state = {'job_id':job_id, 'job':job, 'outputs':outputs, 'phase':'submission-intent',
                     'task_progress': task_progress(request)}
            _save(run_id, state, 'accepted')
        try:
            job = client.query_job(state['job_id'])
        except KusciaError as exc:
            if not any(v in str(exc).lower() for v in ('not found', 'not exist')):
                raise
            client.create_job(state['job'])
            job = client.query_job(state['job_id'])
        raw = str((job.get('status') or {}).get('state') or job.get('state') or '').lower()
        status = 'succeeded' if raw in ('succeeded','finished') else 'failed' if raw in ('failed','approvalreject') else 'cancelled' if raw in ('cancelled','canceled') else 'running'
        state['phase'] = 'submitted'
        state['engine_state'] = raw
        state['task_progress'] = task_progress(request, job)
        outputs = [v for node in state['outputs'].values() for v in node.values()]
        state['result'] = {'outputs':state['outputs'], 'output_uri':outputs[0]['relative_uri'].removeprefix('/home/kuscia/var/storage/data/') if len(outputs)==1 else None,
                           'output_format':outputs[0]['format'] if len(outputs)==1 else None}
        _save(run_id,state,status, str((job.get('status') or {}).get('message') or raw) if status=='failed' else None)
        return {'status':status, 'external_run_ref':state['job_id'], 'result':state['result']}
    except DispatchError as exc:
        # A definitive rejection before submission cannot recover by retrying.
        # Preserve uncertain transport/submission outcomes for reconciliation.
        if exc.retryable or state.get('job'):
            raise
        message = f"连接器 {exc.connector_id} 输入准备失败：{exc.message}"
        state.update({'phase': 'preparation-failed', 'error': message})
        _save(run_id, state, 'failed', message)
        return {'status': 'failed', 'error': message}
    except ValueError as exc:
        # Declarative compilation/snapshot conflicts are deterministic. Retrying
        # them forever would leave the UI stuck in accepted with no engine job.
        if state.get('job'):raise
        message=str(exc)
        state.update({'phase':'compilation-failed','error':message})
        _save(run_id,state,'failed',message)
        return {'status':'failed','error':message}
    finally:
        client.close()

def refresh_task_progress(run_id):
    """Enrich historical runs without changing outcome, approvals or usage."""
    with SessionLocal() as db:
        row, attr, _, _ = _load(db, run_id)
        if row is None:
            return
        record = getattr(row, attr) or {}
        request = record.get('execution_request') or {}
        state = record.get('master_execution') or {}
        job_id = state.get('job_id')
        if request.get('scheduling_mode') != 'master-lite' or not job_id:
            return
    client = get_kuscia_client()
    try:
        progress = task_progress(request, client.query_job(job_id))
    except KusciaError:
        return  # Keep the last observed counts if the engine is unavailable.
    finally:
        client.close()
    with SessionLocal() as db:
        # Cleanup and reconciliation can also update this JSON document.
        # Merge into its latest locked value instead of writing a stale snapshot.
        row, attr, _, _ = _load(db, run_id)
        if row is None:
            return
        db.refresh(row, with_for_update=True)
        record = getattr(row, attr) or {}
        setattr(row, attr, {**record, 'master_execution': {
            **(record.get('master_execution') or {}), 'task_progress': progress}})
        db.commit()

def reconcile_once():
    with SessionLocal() as db:
        pending = []
        for model, attr in ((PrivacyComputeRun,'evidence'),(ProjectRun,'job_snapshot')):
            for row in db.scalars(select(model).where(model.status.in_(['pending-dispatch','accepted','running']))).all():
                record = getattr(row,attr) or {}
                if (record.get('execution_request') or {}).get('scheduling_mode') != 'master-lite':
                    continue  # Existing autonomy runs are not silently rebound.
                pending.append((row.id, record.get('execution_request') or {}))
    for run_id, request in pending:
        try:
            dispatch_master_run(run_id, request)
        except Exception:
            # Retry persisted intent; uncertainty must never fabricate a failed job.
            import logging
            logging.getLogger(__name__).warning('Master reconciliation deferred for run %s',run_id)
    with SessionLocal() as db:
        terminal=[]
        for model, attr in ((PrivacyComputeRun,'evidence'),(ProjectRun,'job_snapshot')):
            for row in db.scalars(select(model).where(model.status.in_(list(TERMINAL)))):
                record=getattr(row,attr) or {}
                if record.get('artifact_lifecycle',{}).get('state')!='cleaned':
                    terminal.append((row.id,record.get('execution_request') or {}))
    for run_id,request in terminal:
        try:reconcile_artifacts(run_id,request)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Artifact cleanup pending for run %s',run_id)



def reconcile_artifacts(run_id, request):
    """Durable per-domain acknowledgements; an unreachable domain is never deleted."""
    from app.services.execution_dispatch import _post, _endpoint
    with SessionLocal() as db:
        row,attr,_,_=_load(db,run_id)
        if not row or row.status not in TERMINAL or 'artifact_plan' not in request:return
        snapshot=dict(getattr(row,attr) or {});lifecycle=dict(snapshot.get('artifact_lifecycle') or {})
        if lifecycle.get('state')=='cleaned':return
        state=snapshot.get('master_execution') or {}
        receipts=dict(lifecycle.get('receipts') or {});verify=dict(lifecycle.get('verified') or {})
        job_id=state.get('job_id') or 'kuscia-'+hashlib.sha256(run_id.encode()).hexdigest()[:28]
        expected={_engine_task_id(job_id,n['id']) for n in request.get('workflow',{}).get('nodes',[])}
        reference_scope=set()
        try:
            for participant in request.get('participants',[]):
                cid=participant['connector_id']
                try:scope=_post(_endpoint(participant['connector_endpoint'],cid),run_id,cid,'artifacts',{'connector_id':cid,'phase':'scope'},30)
                except Exception as exc:
                    if not state.get('job_id') and getattr(exc,'status_code',None)==404:continue
                    raise
                refs=scope.get('reference_scope')
                if scope.get('run_id')!=run_id or scope.get('connector_id')!=cid or not isinstance(refs,list) or not all(isinstance(r,str) and r for r in refs):
                    raise ValueError('连接器输入引用范围无效')
                reference_scope.update(refs)
        except Exception as exc:
            lifecycle.update(state='pending-confirmation',errors={'scope':str(exc)[:400]})
            snapshot['artifact_lifecycle']=lifecycle;setattr(row,attr,snapshot);db.commit();return
        reference_scope=sorted(reference_scope)
        client=get_kuscia_client()
        try:
            proof=client.job_quiescence(job_id,sorted(expected),reference_scope)
            created=proof.get('created_task_ids');never=proof.get('never_created_task_ids')
            if (proof.get('job_id')!=job_id or proof.get('terminal') is not True or proof.get('completed') is not True
                    or not isinstance(created,list) or not isinstance(never,list)
                    or set(created)&set(never) or len(created)!=len(set(created)) or len(never)!=len(set(never))
                    or set(created)|set(never)!=expected or proof.get('references_clear') is not True
                    or proof.get('reference_scope')!=reference_scope or proof.get('reference_hash')!=hashlib.sha256(json.dumps(reference_scope,separators=(',',':')).encode()).hexdigest()):
                raise ValueError('引擎尚未提供完整停止证明')
        except Exception as exc:
            lifecycle.update(state='pending-confirmation',errors={'master':str(exc)[:400]})
            snapshot['artifact_lifecycle']=lifecycle;setattr(row,attr,snapshot);db.commit();return
        finally:client.close()
        lifecycle['stop_proof']=proof
        errors={}
        for p in request.get('participants',[]):
            cid=p['connector_id']
            try:
                if row.status=='succeeded' and cid not in verify:
                    verify[cid]=_post(_endpoint(p['connector_endpoint'],cid),run_id,cid,'artifacts',{'connector_id':cid,'phase':'verify'},30)
            except Exception as exc:errors[cid]=str(exc)[:400]
        # Preserve everything if a successful run's final output has not been verified.
        if row.status!='succeeded' or len(verify)==len(request.get('participants',[])):
            for p in request.get('participants',[]):
                cid=p['connector_id']
                if cid in receipts:continue
                try:receipts[cid]=_post(_endpoint(p['connector_endpoint'],cid),run_id,cid,'artifacts',{'connector_id':cid,'phase':'cleanup','tasks_stopped':True,'stop_proof':proof},30)
                except Exception as exc:
                    # Before engine submission, a 404 proves this domain never
                    # persisted a preparation record. A submitted job's missing
                    # record is uncertainty and must remain pending.
                    if not state.get('job_id') and getattr(exc,'status_code',None)==404:
                        receipts[cid]={'state':'not-prepared','connector_id':cid}
                    else:errors[cid]=str(exc)[:400]
        lifecycle.update(state='cleaned' if len(receipts)==len(request.get('participants',[])) else 'pending-confirmation',receipts=receipts,verified=verify,errors=errors)
        snapshot['artifact_lifecycle']=lifecycle;setattr(row,attr,snapshot);db.commit()

