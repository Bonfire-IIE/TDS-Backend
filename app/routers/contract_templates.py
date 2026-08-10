"""contract_templates 模块：合约模板（系统预置 + 用户自建）的增删改查。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.contract_template import ContractTemplate
from app.schemas.contract_template import TemplateCreate, TemplateOut, TemplateUpdate
from app.services import contract_template as svc

router = APIRouter(prefix="/contract-templates", tags=["contract-templates"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(r: ContractTemplate) -> TemplateOut:
    return TemplateOut.model_validate(r)


@router.get("")
def list_templates(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_templates(db, user["username"])
    return _wrap([_out(r) for r in items])


@router.post("", status_code=201)
def create_template(
    body: TemplateCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.create(db, user["username"], _is_operator(user), body)
    except svc.TemplateError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.get("/{template_id}")
def get_template(
    template_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.get(db, template_id, user["username"], _is_operator(user))
    except svc.TemplateError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.put("/{template_id}")
def update_template(
    template_id: str,
    body: TemplateUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.update(db, template_id, user["username"], _is_operator(user), body)
    except svc.TemplateError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.delete(db, template_id, user["username"], _is_operator(user))
    except svc.TemplateError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({"id": template_id})
