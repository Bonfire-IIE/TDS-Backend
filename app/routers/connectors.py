"""connector 模块：连接器注册审批与部署指引。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.connector import Connector
from app.schemas.connector import (
    ConnectorApply,
    ConnectorImport,
    ConnectorOut,
    DeployInfo,
    ConnectorUpdate,
    NodeInfoReport,
)
from app.services import connector as svc

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _require_operator(user: dict = Depends(get_current_user)) -> dict:
    if not _is_operator(user):
        raise HTTPException(status_code=403, detail="需要运营方(operator)权限")
    return user


def _out(c: Connector) -> ConnectorOut:
    o = ConnectorOut.model_validate(c)
    o.status = svc.display_status(c)  # 派生实时在线态
    return o


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


@router.post("", status_code=201)
def apply(
    body: ConnectorApply,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="管理员/超管不可申请连接器，请使用普通参与方账户创建",
        )
    try:
        c = svc.apply(db, user["username"], body)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.get("")
def list_connectors(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_for(db, user["username"], _is_admin(user))
    return _wrap([_out(c) for c in items])


@router.get("/{connector_id}")
def get_connector(
    connector_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.get(db, connector_id)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    if c.created_by != user["username"] and not _is_admin(user):
        raise HTTPException(status_code=403, detail="无权访问")
    return _wrap(_out(c))


@router.delete("/{connector_id}")
def delete_connector(
    connector_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.get(db, connector_id)
        if c.created_by != user["username"] and not _is_admin(user):
            raise svc.ConnectorError("无权删除该连接器", 403)
        svc.soft_delete(db, connector_id)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(None)


@router.patch("/{connector_id}")
def update_connector(connector_id: str, body: ConnectorUpdate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        if c.created_by != user["username"]:
            raise svc.ConnectorError("无权修改该连接器", 403)
        if c.status not in ("applying", "approved"):
            raise svc.ConnectorError("当前状态不可修改连接器信息", 409)
        c.name, c.org_name = body.name, body.org_name
        c.lite_api_endpoint, c.lite_api_port = body.lite_api_endpoint, body.lite_api_port
        c.auth_port, c.grpc_port = body.auth_port, body.grpc_port
        c.app_port, c.data_port = body.app_port, body.data_port
        db.commit(); db.refresh(c)
        return _wrap(_out(c))
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.post("/{connector_id}/node-info")
def report_node_info(
    connector_id: str,
    body: NodeInfoReport,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """连接器门户部署完 Lite 后回传节点物理地址/端口（供 CDR 用物理 endpoint）。"""
    try:
        c = svc.report_node_info(db, connector_id, user["username"], _is_admin(user), body)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.post("/import", status_code=201)
def import_existing(
    body: ConnectorImport,
    user: dict = Depends(_require_operator),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.import_existing(db, user["username"], body)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.post("/{connector_id}/approve")
def approve(
    connector_id: str,
    user: dict = Depends(_require_operator),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.approve(db, connector_id)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.post("/{connector_id}/reject")
def reject(
    connector_id: str,
    user: dict = Depends(_require_operator),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.reject(db, connector_id)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


def _load_owned(connector_id: str, user: dict, db: Session) -> Connector:
    try:
        c = svc.get(db, connector_id)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    if c.created_by != user["username"]:
        raise HTTPException(status_code=403, detail="无权访问")
    return c


@router.get("/{connector_id}/deploy", response_model=None)
def deploy_info(
    connector_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    c = _load_owned(connector_id, user, db)
    try:
        info = svc.deploy_info(c)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(DeployInfo(**info))


@router.get("/{connector_id}/deploy/script")
def deploy_script(
    connector_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    c = _load_owned(connector_id, user, db)
    try:
        script = svc.deploy_script(c)
    except svc.ConnectorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    fname = f"deploy-connector-{c.kuscia_domain_id}.sh"
    return Response(
        content=script,
        media_type="application/x-shellscript",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
