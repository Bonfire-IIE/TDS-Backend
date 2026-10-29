"""连接器软件部署和机器身份注册。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.connector import Connector
from app.schemas.connector import (
    ConnectorActivate,
    ConnectorApply,
    ConnectorCertificateOut,
    ConnectorImport,
    ConnectorOut,
    ConnectorUpdate,
    DeploymentInstructionOut,
)
from app.services import connector as svc
from app.services.connector_identity import certificate_fingerprint

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _require_operator(user: dict = Depends(get_current_user)) -> dict:
    if not _is_operator(user):
        raise HTTPException(403, "需要运营方(operator)权限")
    return user


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(c: Connector) -> ConnectorOut:
    return ConnectorOut.model_validate(c)


def _owned(c: Connector, user: dict, allow_admin: bool = True) -> None:
    if c.created_by != user["username"] and not (allow_admin and _is_admin(user)):
        raise HTTPException(403, "无权访问该连接器")


@router.get("/deployment-instructions")
def deployment_instructions(
    system: str = Query("linux"),
    deployment_platform: str = Query("docker-compose"),
    architecture: str = Query("amd64"),
    version: str = Query("latest", pattern=r"^[A-Za-z0-9._-]+$"),
    _: dict = Depends(get_current_user),
) -> dict:
    try:
        data = svc.deployment_instructions(system, deployment_platform, architecture, version)
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return _wrap(DeploymentInstructionOut(**data))


@router.get("/downloads/{version}/docker-compose.yml", include_in_schema=False)
def download_connector_compose(
    version: str,
) -> Response:
    """Download the versioned, Kuscia-free v2 connector runtime bundle."""
    try:
        payload = svc.connector_compose(version)
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return Response(
        content=payload,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="docker-compose.yml"'},
    )


@router.get("/downloads/{version}/connector-runtime.tar.gz", include_in_schema=False)
def download_connector_runtime(version: str) -> FileResponse:
    if not version or not version.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise HTTPException(422, "连接器版本标识无效")
    asset = Path(__file__).resolve().parents[1] / "deployment_assets" / "connector-runtime-v2.tar.gz"
    if not asset.is_file():
        raise HTTPException(503, "连接器运行包尚未发布")
    return FileResponse(
        asset,
        media_type="application/gzip",
        filename="connector-runtime.tar.gz",
    )


@router.post("", status_code=201)
def apply(body: ConnectorApply, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if _is_admin(user):
        raise HTTPException(403, "管理员/超管不可申请连接器，请使用普通参与方账户创建")
    try:
        return _wrap(_out(svc.apply(db, user["username"], body)))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("")
def list_connectors(user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _wrap([_out(c) for c in svc.list_for(db, user["username"], _is_admin(user))])


@router.post("/import", status_code=201)
def import_existing(body: ConnectorImport, user: dict = Depends(_require_operator), db: Session = Depends(get_db)) -> dict:
    try:
        return _wrap(_out(svc.import_existing(db, user["username"], body)))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/{connector_id}")
def get_connector(connector_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        _owned(c, user)
        return _wrap(_out(c))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.patch("/{connector_id}")
def update_connector(connector_id: str, body: ConnectorUpdate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        _owned(c, user, allow_admin=False)
        if c.status not in {"applying", "approved", "active"}:
            raise svc.ConnectorError("当前状态不可修改连接器信息", 409)
        c.name, c.org_name = body.name, body.org_name
        db.commit()
        db.refresh(c)
        return _wrap(_out(c))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/{connector_id}/approve")
def approve(connector_id: str, _: dict = Depends(_require_operator), db: Session = Depends(get_db)) -> dict:
    try:
        return _wrap(_out(svc.approve(db, connector_id)))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/{connector_id}/reject")
def reject(connector_id: str, _: dict = Depends(_require_operator), db: Session = Depends(get_db)) -> dict:
    try:
        return _wrap(_out(svc.reject(db, connector_id)))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/{connector_id}/certificate")
def get_certificate(connector_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        _owned(c, user, allow_admin=False)
        c, ca_pem = svc.certificate(db, connector_id)
        return _wrap(ConnectorCertificateOut(
            connector_id=c.id,
            certificate_pem=c.certificate_pem or "",
            ca_certificate_pem=ca_pem,
            fingerprint=certificate_fingerprint(c.certificate_pem or ""),
            not_after=c.certificate_not_after,
        ))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/{connector_id}/activate")
def activate(connector_id: str, body: ConnectorActivate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        _owned(c, user, allow_admin=False)
        return _wrap(_out(svc.activate(db, connector_id, body.certificate_fingerprint)))
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.delete("/{connector_id}")
def delete_connector(connector_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        c = svc.get(db, connector_id)
        _owned(c, user)
        svc.soft_delete(db, connector_id)
        return _wrap(None)
    except svc.ConnectorError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
