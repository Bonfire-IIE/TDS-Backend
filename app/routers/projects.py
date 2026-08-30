from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import ProjectRun,WorkflowApproval,WorkflowVersion
from app.schemas.project import ApprovalOut,ApprovalRequest,AvailableDomainDataOut,DomainOut,ProjectCreate,ProjectOut,RunCreate,RunOut,VersionOut,WorkflowSubmit
from app.services import project as svc

router=APIRouter(prefix="/projects",tags=["projects"])
def op(u): return "operator" in u.get("roles",[])
def admin(u): return bool({"operator","supervisor"} & set(u.get("roles",[])))
def wrap(x): return {"code":0,"message":"ok","data":x}
def guard(fn):
    try: return fn()
    except svc.ProjectError as e: raise HTTPException(e.status_code,e.message) from e

@router.get("")
def listing(user=Depends(get_current_user),db:Session=Depends(get_db)):
    return wrap([ProjectOut.model_validate(x) for x in db.scalars(svc._visible(db,user["username"],admin(user)))])

@router.post("",status_code=201)
def create(body:ProjectCreate,user=Depends(get_current_user),db:Session=Depends(get_db)):
    return wrap(ProjectOut.model_validate(guard(lambda:svc.create(db,user["username"],op(user),body))))

def detail_data(db,p):
    domains=svc.project_domains(db,p)
    version=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version==p.current_version)) if p.current_version else None
    previous=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version<p.current_version).order_by(WorkflowVersion.version.desc())) if (p.current_version and p.current_version>1) else None
    approvals=list(db.scalars(select(WorkflowApproval).where(WorkflowApproval.workflow_version_id==version.id))) if version else []
    runs=list(db.scalars(select(ProjectRun).where(ProjectRun.project_id==p.id).order_by(ProjectRun.created_at.desc())))
    return {"project":ProjectOut.model_validate(p),"domains":[DomainOut(connector_id=x.id,domain_id=x.kuscia_domain_id) for x in domains],"current_workflow":VersionOut.model_validate(version) if version else None,"previous_workflow":VersionOut.model_validate(previous) if previous else None,"approvals":[ApprovalOut.model_validate(x) for x in approvals],"runs":[RunOut.model_validate(x) for x in runs],"connectivity":svc.connectivity_status(db,p)}

@router.get("/{project_id}")
def detail(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); return wrap(detail_data(db,p))

@router.post("/{project_id}/workflows")
def workflow(project_id:str,body:WorkflowSubmit,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); row=guard(lambda:svc.submit(db,p,user["username"],body.workflow)); return wrap(VersionOut.model_validate(row))

@router.post("/{project_id}/approvals")
def approval(project_id:str,body:ApprovalRequest,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); guard(lambda:svc.approve(db,p,user["username"],op(user),body)); return wrap(detail_data(db,p))

@router.get("/{project_id}/connectivity")
def connectivity(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); return wrap(svc.connectivity_status(db,p))

@router.get("/{project_id}/available-domain-data")
def available_domain_data(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user)))
    return wrap([AvailableDomainDataOut(**x) for x in svc.available_domain_data(db,p,user["username"],op(user))])

@router.post("/{project_id}/connectivity/ensure")
def connectivity_ensure(project_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); return wrap(guard(lambda:svc.ensure_connectivity(db,p)))

@router.post("/{project_id}/runs",status_code=201)
def run(project_id:str,body:RunCreate,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); return wrap(RunOut.model_validate(guard(lambda:svc.run(db,p,user["username"],body.idempotency_key))))

@router.post("/{project_id}/runs/{run_id}/refresh")
def refresh(project_id:str,run_id:str,user=Depends(get_current_user),db:Session=Depends(get_db)):
    p=guard(lambda:svc.get(db,project_id,user["username"],admin(user))); row=db.get(ProjectRun,run_id)
    if not row or row.project_id!=p.id: raise HTTPException(404,"运行实例不存在")
    return wrap(RunOut.model_validate(svc.sync_run(db,p,row)))
