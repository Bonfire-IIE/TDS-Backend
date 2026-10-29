"""catalog 模块：接收连接器资源投影、审核与属主目录查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.catalog import DataCatalog
from app.models.capability import DataResourceBinding
from app.schemas.catalog import CatalogOut, ResourcePublish, ResourceBindingReport
from app.services import catalog as svc

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(r: DataCatalog) -> CatalogOut:
    return CatalogOut.model_validate(r)


@router.get("/code-dict")
def code_dict(db: Session = Depends(get_db), _: dict = Depends(get_current_user)) -> dict:
    return _wrap(svc.get_code_tables(db))


@router.post("/resources/publish", status_code=201)
def publish_resource(
    body: ResourcePublish,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.publish_resource(db, user["username"], body)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.get("/resources")
def search_resources(
    q: str | None = Query(None),
    security_level: str | None = Query(None),
    industry_code: str | None = Query(None),
    connector_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = svc.search(
        db, user["username"], _is_admin(user),
        q=q, security_level=security_level,
        industry_code=industry_code, connector_id=connector_id,
    )
    return _wrap([_out(r) for r in items])


@router.post("/resources/{catalog_id}/approve")
def approve_resource(
    catalog_id: str,
    body: dict | None = None,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="仅中心管理员可以审核资源上架")
    try:
        r = svc.approve_resource(db, catalog_id, (body or {}).get("comment"))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.post("/resources/{catalog_id}/reject")
def reject_resource(
    catalog_id: str,
    body: dict,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="仅中心管理员可以审核资源上架")
    comment = str((body or {}).get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="驳回时必须填写审核意见")
    try:
        r = svc.reject_resource(db, catalog_id, comment)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.get("/resources/{catalog_id}")
def get_resource(
    catalog_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.get(db, catalog_id)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    # 普通用户仅能查看自有资源；admin 可查看全部
    if r.created_by != user["username"] and not _is_admin(user):
        raise HTTPException(status_code=403, detail="无权查看该资源")
    return _wrap(_out(r))


@router.delete("/resources/{catalog_id}")
def delete_resource(
    catalog_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.delete_resource(db, catalog_id, user["username"], _is_admin(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({"withdrawn": catalog_id, "status": "delisted"})


@router.post("/resources/{catalog_id}/delist")
def delist_resource(
    catalog_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.delist(db, catalog_id, user["username"], _is_admin(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.post("/resources/{catalog_id}/bindings", status_code=201)
def report_resource_binding(
    catalog_id: str,
    body: ResourceBindingReport,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if body.connector_id == "":
        raise HTTPException(400, "connector_id 不能为空")
    # The path resource is authoritative; do not allow a client to report a
    # binding for a different platform resource.
    body = body.model_copy(update={"platform_resource_id": catalog_id}) if hasattr(body, "model_copy") else body
    try:
        binding = svc.report_resource_binding(db, user["username"], body)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({
        "id": binding.id,
        "platform_resource_id": binding.platform_resource_id,
        "connector_id": binding.connector_id,
        "connector_resource_ref": binding.connector_resource_ref,
        "version": binding.version,
        "sync_status": binding.sync_status,
        "last_synced_at": binding.last_synced_at,
    })


@router.get("/resources/{catalog_id}/bindings")
def list_resource_bindings(
    catalog_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return generic connector bindings; no downstream-system identifiers are exposed."""
    resource = db.get(DataCatalog, catalog_id)
    if not resource or resource.deleted_at is not None:
        raise HTTPException(404, "平台资源不存在")
    if resource.created_by != user["username"] and not _is_admin(user):
        raise HTTPException(403, "无权查看该资源绑定")
    rows = db.scalars(select(DataResourceBinding).where(
        DataResourceBinding.platform_resource_id == catalog_id
    ).order_by(DataResourceBinding.created_at)).all()
    return _wrap([{
        "id": row.id,
        "platform_resource_id": row.platform_resource_id,
        "connector_id": row.connector_id,
        "connector_resource_ref": row.connector_resource_ref,
        "source": row.source,
        "version": row.version,
        "sync_status": row.sync_status,
        "metadata_snapshot": row.metadata_snapshot,
        "last_synced_at": row.last_synced_at,
    } for row in rows])
