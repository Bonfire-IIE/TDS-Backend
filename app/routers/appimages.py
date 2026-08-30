"""appimages 模块：应用能力(AppImage)纳管、注册、检索、下架。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.appimage import AppImage
from app.schemas.appimage import AppImageCreate, AppImageOut, AppImageParseRequest
from app.services import appimage as svc

router = APIRouter(prefix="/appimages", tags=["appimages"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(r: AppImage) -> AppImageOut:
    return AppImageOut.model_validate(r)


@router.get("")
def list_appimages(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_appimages(db, user["username"], _is_admin(user))
    return _wrap([_out(r) for r in items])


@router.post("", status_code=201)
def register_appimage(
    body: AppImageCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.register(db, user["username"], _is_operator(user), body)
    except svc.AppImageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.post("/parse")
def parse_appimage_config(
    body: AppImageParseRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    try:
        return _wrap(svc.parse_config(body.content, body.kind))
    except svc.AppImageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.get("/{appimage_id}")
def get_appimage(
    appimage_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.get(db, appimage_id)
    except svc.AppImageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.post("/{appimage_id}/delist")
def delist_appimage(
    appimage_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.delist(db, appimage_id, user["username"], _is_admin(user))
    except svc.AppImageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))

@router.put("/{appimage_id}")
def update_appimage(appimage_id: str, body: AppImageCreate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        r = svc.update(db, appimage_id, user["username"], _is_operator(user), body)
    except svc.AppImageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))
