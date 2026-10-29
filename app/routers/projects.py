from app.core.config import settings
from fastapi import APIRouter,BackgroundTasks,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import SessionLocal,get_db
from app.core.execution_auth import dispatch_configured
from app.core.security import get_current_user
from app.models import Project,ProjectRun,WorkflowApproval,WorkflowVersion
from app.services import usage
from app.schemas.project import ApprovalOut,ApprovalRequest,AvailableDomainDataOut,DomainOut,ProjectCreate,ProjectOut,RunOut,VersionOut,WorkflowSubmit
from app.services import project as svc
from app.services.execution_dispatch import DispatchError, dispatch_run

router=APIRouter(prefix="/projects",tags=["projects"])
def op(u): return "operator" in u.get("roles",[])
def wrap(x): return {"code":0,"message":"ok","data":x}
def guard(fn):
    try: return fn()
    except (svc.ProjectError, svc.templates.TemplateError) as e: raise HTTPException(e.status_code,e.message) from e

@router.get("")
def listing(user=Depends(get_current_user),db:Session=Depends(get_db)):
    return wrap([ProjectOut.model_validate(x) for x in db.scalars(svc._visible(db,user["username"],op(user)))])

@router.post("",status_code=201)
def create(body:ProjectCreate,user=Depends(get_current_user),db:Session=Depends(get_db)):
    return wrap(ProjectOut.model_validate(guard(lambda:svc.create(db,user["username"],op(user),body))))

def detail_data(db,p):
    domains=svc.project_domains(db,p)
    provider_id, consumer_id, _ = svc.contract_input_scope(db, p)
    version=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version==p.current_version)) if p.current_version else None
    previous=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version<p.current_version).order_by(WorkflowVersion.version.desc())) if (p.current_version and p.current_version>1) else None
    approvals=list(db.scalars(select(WorkflowApproval).where(WorkflowApproval.workflow_version_id==version.id))) if version else []
    runs=list(db.scalars(select(ProjectRun).where(ProjectRun.project_id==p.id).order_by(ProjectRun.created_at.desc())))
    return {"project":ProjectOut.model_validate(p),"domains":[DomainOut(connector_id=x.id,domain_id=x.id,connector_name=x.name,org_name=x.org_name,contract_role="provider" if x.id==provider_id else "consumer" if x.id==consumer_id else None) for x in domains],"current_workflow":VersionOut.model_validate(version) if version else None,"previous_workflow":VersionOut.model_validate(previous) if previous else None,"approvals":[ApprovalOut.model_validate(x) for x in approvals],"runs":[RunOut.model_validate(x) for x in runs],"connectivity":svc.connectivity_status(db,p)}

# Static routes precede project ID routes. Identifiers locate a run, never grant data access.
@router.get('/results/local')
def local_results(connector_id:str, limit:int=50, offset:int=0, user=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services import project_results as results
    guard(lambda:results.owned_connector(db,connector_id,user['username']))
    if not 1<=limit<=100 or offset<0:raise HTTPException(422,'无效分页参数')
    # Scope and paginate in SQL so large histories do not hide older local executions.
    statement=select(ProjectRun).where(ProjectRun.job_snapshot['execution_snapshot']['workflow']['nodes'].as_string().contains(connector_id)).order_by(ProjectRun.created_at.desc()).offset(offset).limit(limit)
    rows=list(db.scalars(statement))
    return wrap([results.local_view(db,row,connector_id) for row in rows if results.local_nodes(row,connector_id)])

@router.post('/results/resolve')
def resolve_result(body:dict,user=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services import project_results as results
    cid=str(body.get('connector_id') or '')
    guard(lambda:results.owned_connector(db,cid,user['username']))
    identifier=body.get('execution_id')
    if not isinstance(identifier,str) or not identifier.strip() or len(identifier)>128:raise HTTPException(422,'请输入有效的执行请求编号')
    identifier=identifier.strip()
    row=db.scalar(select(ProjectRun).where((ProjectRun.kuscia_job_id==identifier)|(ProjectRun.id==identifier)))
    if not row:raise HTTPException(404,'执行记录不存在')
    return wrap(guard(lambda:results.local_view(db,row,cid)))

@router.get('/results/local/{run_id}')
def local_result(run_id:str,connector_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services import project_results as results
    guard(lambda:results.owned_connector(db,connector_id,user['username']))
    row=db.get(ProjectRun,run_id)
    if not row:raise HTTPException(404,'执行记录不存在')
    return wrap(guard(lambda:results.local_view(db,row,connector_id)))

@router.get("/{project_id}")
def detail(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user))); return wrap(detail_data(db,p))

@router.post("/{project_id}/workflows")
def workflow(project_id:str,body:WorkflowSubmit,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user))); row=guard(lambda:svc.submit(db,p,user["username"],body.workflow)); return wrap(VersionOut.model_validate(row))

@router.post("/{project_id}/approvals")
def approval(project_id:str,body:ApprovalRequest,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user))); guard(lambda:svc.approve(db,p,user["username"],op(user),body)); return wrap(detail_data(db,p))

@router.get("/{project_id}/connectivity")
def connectivity(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user))); return wrap(svc.connectivity_status(db,p))

@router.get("/{project_id}/available-domain-data")
def available_domain_data(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user)))
    return wrap([AvailableDomainDataOut(**x) for x in guard(lambda: svc.available_domain_data(db,p,user["username"],op(user)))])

def _probe_connectivity(project_id):
    with SessionLocal() as db:
        p=db.get(Project,project_id)
        if not p:return
        try:svc.ensure_connectivity(db,p)
        except Exception as exc:
            db.rollback()
            svc.fail_connectivity_probe(db,p,str(exc))

@router.post("/{project_id}/connectivity/ensure",status_code=202)
def connectivity_ensure(project_id:str,background:BackgroundTasks,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user)))
    value=guard(lambda:svc.begin_connectivity_probe(db,p))
    background.add_task(_probe_connectivity,p.id)
    return wrap(value)


def _fail_dispatch(run_id:str,connector_id:str,message:str)->None:
    with SessionLocal() as db:
        row=db.get(ProjectRun,run_id)
        if not row or row.status not in {"pending-dispatch","accepted","running"}: return
        row.status="failed"
        row.failure_info={"source":"connector_gateway","connector_id":connector_id,"message":message}
        usage_record_ids=(row.job_snapshot or {}).get("usage_record_ids") or []
        legacy_id=(row.job_snapshot or {}).get("usage_record_id")
        usage_record_ids = usage_record_ids or ([legacy_id] if legacy_id else [])
        usage.compensate_many(db,usage_record_ids,"连接器调度失败")
        project=db.get(Project,row.project_id)
        if project: project.status="failed"
        db.commit()


def _dispatch_run(run_id:str,request:dict)->None:
    try:
        dispatch_run(run_id,request)
    except DispatchError as exc:
        _fail_dispatch(run_id,exc.connector_id,exc.message)
    except Exception as exc:
        _fail_dispatch(run_id,str(request.get("dispatch_connector_id") or ""),str(exc))


@router.post("/{project_id}/runs",status_code=201)
def run(project_id:str,background_tasks:BackgroundTasks,user=Depends(get_current_user),db:Session=Depends(get_db)):
    if not dispatch_configured(): raise HTTPException(503,"执行通道未配置：需要管理员设置至少 32 字符的随机密钥")
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user)))
    row=guard(lambda:svc.run(db,p,user["username"]))
    request=(row.job_snapshot or {}).get("execution_request") or {}
    if settings.pets_scheduler_mode != "master-lite":
        background_tasks.add_task(_dispatch_run,row.id,request)
    return wrap(RunOut.model_validate(row))

@router.post("/{project_id}/runs/{run_id}/refresh")
def refresh(project_id:str,run_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],op(user))); row=db.get(ProjectRun,run_id)
    if not row or row.project_id!=p.id: raise HTTPException(404,"运行实例不存在")
    return wrap(RunOut.model_validate(svc.sync_run(db,p,row)))

@router.post('/{project_id}/runs/{run_id}/cancel')
def cancel_run(project_id:str,run_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user['username'],op(user)))
    if p.created_by!=user['username']:raise HTTPException(403,'仅项目发起方可取消执行')
    row=db.get(ProjectRun,run_id)
    if not row or row.project_id!=p.id:raise HTTPException(404,'运行不存在')
    if row.status not in {'pending-dispatch','accepted','running'}:raise HTTPException(409,'执行已终结')
    row.job_snapshot={**row.job_snapshot,'cancel_requested':True};db.commit()
    return wrap(RunOut.model_validate(row))

@router.post('/{project_id}/runs/{run_id}/retry',status_code=201)
def retry_run(project_id:str,run_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user['username'],op(user)));old=db.get(ProjectRun,run_id)
    if not old or old.project_id!=p.id:raise HTTPException(404,'运行不存在')
    if old.status not in {'failed','cancelled'}:raise HTTPException(409,'仅失败或已取消执行允许整体重跑')
    if 'artifact_plan' in (old.job_snapshot.get('execution_request') or {}) and old.job_snapshot.get('artifact_lifecycle',{}).get('state')!='cleaned':raise HTTPException(409,'请等待旧尝试任务停止并完成清理')
    row=guard(lambda:svc.run(db,p,user['username']))
    row.job_snapshot={**row.job_snapshot,'retry_of':old.id,'attempt':int(old.job_snapshot.get('attempt',1))+1};db.commit()
    return wrap(RunOut.model_validate(row))
