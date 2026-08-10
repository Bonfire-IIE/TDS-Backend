"""catalog 模块：数据资源登记与目录检索。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.catalog import DataCatalog
from app.models.datasource import DataSource
from app.schemas.catalog import CatalogOut, DataSourceCreate, DataSourceOut, DataSourceReport, ResourceCreate
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


def _ds_out(r) -> DataSourceOut:
    return DataSourceOut.model_validate(r)


@router.get("/code-dict")
def code_dict(db: Session = Depends(get_db), _: dict = Depends(get_current_user)) -> dict:
    return _wrap(svc.get_code_tables(db))


@router.post("/resources", status_code=201)
def register_resource(
    body: ResourceCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.register_resource(db, user["username"], _is_operator(user), body)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.get("/resources")
def search_resources(
    q: str | None = Query(None),
    security_level: str | None = Query(None),
    resource_category: str | None = Query(None),
    connector_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = svc.search(
        db, user["username"], _is_admin(user),
        q=q, security_level=security_level,
        resource_category=resource_category, connector_id=connector_id,
    )
    return _wrap([_out(r) for r in items])


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
    return _wrap({"deleted": catalog_id})


@router.post("/resources/{catalog_id}/delist")
def delist_resource(
    catalog_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.delist(db, catalog_id, user["username"], _is_operator(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


# ---- 数据源 ----
@router.post("/datasources", status_code=201)
def create_datasource(
    body: DataSourceCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.create_datasource(db, user["username"], _is_operator(user), body)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_ds_out(r))


@router.get("/datasources")
def list_datasources(
    connector_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = svc.list_datasources(db, user["username"], _is_operator(user), connector_id)
    return _wrap([_ds_out(r) for r in items])


@router.get("/datasources/{datasource_id}")
def get_datasource(
    datasource_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.get_datasource(db, datasource_id, user["username"], _is_operator(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_ds_out(r))


@router.delete("/datasources/{datasource_id}")
def delete_datasource(
    datasource_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.delete_datasource(db, datasource_id, user["username"], _is_operator(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({"deleted": datasource_id})


# ---- 连接器门户上报（数据源在连接器本地 Lite 创建，中心仅落非密元数据）----
@router.post("/datasources/report", status_code=201)
def report_datasource(
    body: DataSourceReport,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.report_datasource(db, user["username"], _is_admin(user), body)
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_ds_out(r))


@router.delete("/datasources/{datasource_id}/deregister")
def deregister_datasource(
    datasource_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.deregister_datasource(db, datasource_id, user["username"], _is_admin(user))
    except svc.CatalogError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({"deleted": datasource_id})
