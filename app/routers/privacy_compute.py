from __future__ import annotations
from app.core.config import settings

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header

from app.core.execution_auth import dispatch_authorized, dispatch_configured
from app.core.execution_signatures import execution_signer, active_certificate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
from app.core.security import get_current_user, get_optional_current_user
from app.models.privacy_compute import PrivacyComputeProject
from app.schemas.privacy_compute import PrivacyProjectCreate, PrivacyProjectOut, PrivacyRunCreate, PrivacyRunOut
from app.models.privacy_compute import PrivacyComputeRun
from app.models.connector import Connector
from app.models.project import Project, ProjectRun
from app.services import privacy_compute as svc
from app.services import usage
from app.services.execution_dispatch import DispatchError, dispatch_run

router = APIRouter(prefix="/privacy-computing", tags=["privacy-computing"])


def _is_operator(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


@router.get("/gateway/requests")
def gateway_requests(connector_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Return abstract execution requests for a connector execution gateway.

    The response intentionally contains platform resource references only; no
    Kuscia Domain, DomainData or job identifiers are exposed by this API.
    """
    connector = db.get(Connector, connector_id)
    if not connector or connector.deleted_at is not None or connector.status != "active" or connector.created_by != user["username"]:
        raise HTTPException(403, "无权访问该连接器执行请求")
    rows = db.scalars(select(PrivacyComputeRun).where(PrivacyComputeRun.status.in_(["pending-dispatch", "accepted", "running"]))).all()
    data = []
    if settings.pets_scheduler_mode == "master-lite":
        return {"code": 0, "message": "ok", "data": data}
    for row in rows:
        request = (row.evidence or {}).get("execution_request") or {}
        if connector_id in {request.get("provider_connector_id"), request.get("consumer_connector_id")} and row.status in {"pending-dispatch", "accepted"}:
            data.append({"run_id": row.id, "status": row.status, **request})
        elif request.get("dispatch_connector_id") == connector_id and row.status == "running":
            data.append({"run_id": row.id, "status": row.status, **request})
    project_rows = db.scalars(select(ProjectRun).where(ProjectRun.status.in_(["pending-dispatch", "accepted", "running"]))).all()
    for row in project_rows:
        request = (row.job_snapshot or {}).get("execution_request") or {}
        participants = {request.get("provider_connector_id"), request.get("consumer_connector_id")}
        participants.update(x.get("connector_id") for x in request.get("participants", []) if isinstance(x, dict))
        if connector_id in participants:
            data.append({"run_id": row.id, "status": row.status, **request})
    return {"code": 0, "message": "ok", "data": data}


def _dispatch_authorized(secret: str | None) -> bool:
    return dispatch_authorized(secret)


def _project_status_from_latest_run(db: Session, model, project_id: str) -> str | None:
    latest = db.scalar(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(1)
    )
    if not latest:
        return None
    if latest.status == "succeeded":
        return "completed"
    if latest.status in {"failed", "cancelled"}:
        return "failed"
    return "running"


@router.post("/gateway/runs/{run_id}/report")
def gateway_report(run_id: str, body: dict, signer: str | None = Depends(execution_signer), user: dict | None = Depends(get_optional_current_user), db: Session = Depends(get_db), dispatch_secret: str | None = Header(default=None, alias="X-Bonfire-Execution-Secret")) -> dict:
    # Serialize competing reports on the same run in the production database.
    row = db.get(PrivacyComputeRun, run_id, with_for_update=True)
    project_run = None
    if not row:
        project_run = db.get(ProjectRun, run_id, with_for_update=True)
        if not project_run:
            raise HTTPException(404, "执行请求不存在")
    request = ((row.evidence if row else project_run.job_snapshot) or {}).get("execution_request") or {}
    connector_id = body.get("connector_id")
    if connector_id not in {request.get("provider_connector_id"), request.get("consumer_connector_id")}:
        raise HTTPException(403, "连接器不属于该执行请求")
    connector = db.get(Connector, connector_id)
    if not connector or connector.deleted_at is not None or connector.status != "active" or (signer != connector_id and not _dispatch_authorized(dispatch_secret) and (not user or connector.created_by != user["username"])):
        raise HTTPException(403, "无权回报该执行请求")
    if settings.pets_scheduler_mode == "master-lite":
        raise HTTPException(409, "作业状态由中心 Kuscia Master 对账，连接器不能回报作业终态")
    allowed = {"pending-dispatch", "accepted", "running", "succeeded", "failed", "cancelled"}
    status = str(body.get("status") or "")
    if status not in allowed:
        raise HTTPException(422, "无效的执行状态")
    target = row or project_run
    if status in {"pending-dispatch", "running", "succeeded", "failed", "cancelled"} and connector_id != request.get("dispatch_connector_id"):
        raise HTTPException(403, "只有调度连接器可以回报作业状态")
    terminal = {"succeeded", "failed", "cancelled"}
    if target.status in terminal and status != target.status:
        raise HTTPException(409, "已结束的执行请求不能回退或改变终态")
    if (target.status == "running" and status in {"pending-dispatch", "accepted"}) or (target.status == "accepted" and status == "pending-dispatch"):
        raise HTTPException(409, "运行中的执行请求不能回退到准备阶段")
    external_ref = row.external_run_ref if row else project_run.kuscia_job_id
    if body.get("external_run_ref") and external_ref and not (project_run and external_ref == f"exec-{run_id}") and body["external_run_ref"] != external_ref:
        raise HTTPException(409, "执行请求已绑定其他引擎作业")
    if connector_id != request.get("dispatch_connector_id") and any(body.get(k) is not None for k in ("external_run_ref", "result", "error")):
        raise HTTPException(403, "准备参与方不能修改作业结果")
    if row:
        row.status = status
        row.external_run_ref = body.get("external_run_ref") or row.external_run_ref
        row.result = body.get("result") if body.get("result") is not None else row.result
        row.error = body.get("error")
        row.evidence = {**(row.evidence or {}), "gateway_report": {"connector_id": connector_id, "status": status}}
        project = db.get(PrivacyComputeProject, row.project_id, with_for_update=True)
        run_model = PrivacyComputeRun
        project_id = row.project_id
    else:
        previous_status = project_run.status
        project_run.status = status
        project_run.kuscia_job_id = body.get("external_run_ref") or project_run.kuscia_job_id
        project_run.failure_info = {"message": body.get("error"), "connector_id": connector_id} if body.get("error") else None
        project_run.job_snapshot = {**(project_run.job_snapshot or {}),
            "gateway_report": {"connector_id": connector_id, "status": status},
            "result": body.get("result") if body.get("result") is not None else (project_run.job_snapshot or {}).get("result")}
        project = db.get(Project, project_run.project_id, with_for_update=True)
        run_model = ProjectRun
        project_id = project_run.project_id
    db.flush()
    if not row and status in {"failed", "cancelled"} and previous_status not in {"failed", "cancelled", "succeeded"}:
        snapshot = project_run.job_snapshot or {}
        record_ids = snapshot.get("usage_record_ids") or []
        legacy_id = snapshot.get("usage_record_id")
        usage.compensate_many(db, record_ids or ([legacy_id] if legacy_id else []), body.get("error") or "执行失败")
    if project:
        project.status = _project_status_from_latest_run(db, run_model, project_id) or project.status
    db.commit()
    target = row or project_run
    db.refresh(target)
    data = PrivacyRunOut.model_validate(row) if row else {
        "id": project_run.id, "status": project_run.status,
        "external_run_ref": project_run.kuscia_job_id,
        "result": (project_run.job_snapshot or {}).get("result"),
        "error": (project_run.failure_info or {}).get("message"),
    }
    return {"code": 0, "message": "ok", "data": data}


@router.get("/gateway/runs/{run_id}")
def gateway_run(run_id: str, connector_id: str, signer: str | None = Depends(execution_signer), user: dict | None = Depends(get_optional_current_user), db: Session = Depends(get_db), dispatch_secret: str | None = Header(default=None, alias="X-Bonfire-Execution-Secret")) -> dict:
    connector = db.get(Connector, connector_id)
    if not connector or connector.deleted_at is not None or connector.status != "active" or (
        signer != connector_id and not _dispatch_authorized(dispatch_secret) and (not user or connector.created_by != user["username"])
    ):
        raise HTTPException(403, "无权访问该执行请求")
    row = db.get(PrivacyComputeRun, run_id)
    project_run = None if row else db.get(ProjectRun, run_id)
    if not row and not project_run:
        raise HTTPException(404, "执行请求不存在")
    request = ((row.evidence if row else project_run.job_snapshot) or {}).get("execution_request") or {}
    if connector_id not in {request.get("provider_connector_id"), request.get("consumer_connector_id")}:
        raise HTTPException(403, "连接器不属于该执行请求")
    target = row or project_run
    snapshot = ((row.evidence if row else project_run.job_snapshot) or {}).get("execution_snapshot")
    guidance = request.get("result_guidance") or ((row.evidence if row else project_run.job_snapshot) or {}).get("result_guidance")
    return {"code": 0, "message": "ok", "data": {
        "run_id": target.id, "status": target.status,
        "external_run_ref": row.external_run_ref if row else project_run.kuscia_job_id,
        "execution_request": request,
        "execution_snapshot": snapshot,
        "portal_endpoints": request.get("portal_endpoints") or {},
        "result_guidance": guidance,
    }}


@router.get("/gateway/runs/{run_id}/identity")
def gateway_peer_identity(run_id: str, connector_id: str, peer_connector_id: str,
                          signer: str | None = Depends(execution_signer), db: Session = Depends(get_db)) -> dict:
    if not signer or signer != connector_id:
        raise HTTPException(403, "需要当前连接器机器签名")
    row = db.get(PrivacyComputeRun, run_id)
    project_run = None if row else db.get(ProjectRun, run_id)
    if not row and not project_run:
        raise HTTPException(404, "执行请求不存在")
    request = ((row.evidence if row else project_run.job_snapshot) or {}).get("execution_request") or {}
    parties = {request.get("provider_connector_id"), request.get("consumer_connector_id")}
    if signer not in parties or peer_connector_id not in parties:
        raise HTTPException(403, "机器身份不属于当前执行请求")
    peer = db.get(Connector, peer_connector_id)
    active_certificate(peer)
    return {"code": 0, "data": {"connector_id": peer.id, "certificate_pem": peer.certificate_pem}}


@router.post("/projects", status_code=201)
def create_project(body: PrivacyProjectCreate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        row = svc.create_project(db, user["username"], body)
    except svc.PrivacyComputeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"code": 0, "message": "ok", "data": PrivacyProjectOut.model_validate(row)}


@router.get("/projects")
def list_projects(user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = svc.list_projects(db, user["username"], _is_operator(user))
    return {"code": 0, "message": "ok", "data": [PrivacyProjectOut.model_validate(x) for x in rows]}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = db.get(PrivacyComputeProject, project_id)
    if not row:
        raise HTTPException(404, "隐私计算项目不存在")
    if row.created_by != user["username"] and not _is_operator(user):
        raise HTTPException(403, "无权查看该隐私计算项目")
    return {"code": 0, "message": "ok", "data": PrivacyProjectOut.model_validate(row)}


def _dispatch_privacy_run(run_id: str, request: dict) -> None:
    try:
        dispatch_run(run_id, request)
    except Exception as exc:
        message = exc.message if isinstance(exc, DispatchError) else str(exc)
        with SessionLocal() as db:
            row = db.get(PrivacyComputeRun, run_id)
            if row and row.status in {"pending-dispatch", "accepted", "running"}:
                row.status = "failed"
                row.error = message[:1000]
                db.commit()


@router.post("/projects/{project_id}/runs", status_code=201)
def start_run(project_id: str, body: PrivacyRunCreate, background_tasks: BackgroundTasks,
              user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not dispatch_configured():
        raise HTTPException(503, "执行通道未配置：需要管理员设置至少 32 字符的随机密钥")
    try:
        row = svc.start_run(db, user["username"], _is_operator(user), project_id, body)
    except svc.PrivacyComputeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    request_data = (row.evidence or {}).get("execution_request") or {}
    if settings.pets_scheduler_mode != "master-lite":
        background_tasks.add_task(_dispatch_privacy_run, row.id, request_data)
    return {"code": 0, "message": "ok", "data": PrivacyRunOut.model_validate(row)}


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = db.get(PrivacyComputeProject, project_id)
    if not project:
        raise HTTPException(404, "隐私计算项目不存在")
    if project.created_by != user["username"] and not _is_operator(user):
        raise HTTPException(403, "无权查看该隐私计算项目")
    rows = db.scalars(select(PrivacyComputeRun).where(PrivacyComputeRun.project_id == project_id).order_by(PrivacyComputeRun.created_at.desc())).all()
    return {"code": 0, "message": "ok", "data": [PrivacyRunOut.model_validate(x) for x in rows]}


@router.post("/projects/{project_id}/runs/{run_id}/refresh")
def refresh_run(project_id: str, run_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        row = svc.refresh_run(db, user["username"], _is_operator(user), project_id, run_id)
    except svc.PrivacyComputeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"code": 0, "message": "ok", "data": PrivacyRunOut.model_validate(row)}
