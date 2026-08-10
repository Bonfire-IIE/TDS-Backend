"""products 模块：数据产品上架、目录浏览、下架。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.product import DataProduct
from app.schemas.product import ProductCreate, ProductOut
from app.services import product as svc

router = APIRouter(prefix="/products", tags=["products"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(r: DataProduct) -> ProductOut:
    return ProductOut.model_validate(r)


@router.post("", status_code=201)
def create_product(
    body: ProductCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.create(db, user["username"], _is_admin(user), body)
    except svc.ProductError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.get("")
def list_products(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_products(db, user["username"], _is_admin(user))
    return _wrap([_out(r) for r in items])


@router.get("/{product_id}")
def get_product(
    product_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.get(db, product_id)
    except svc.ProductError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.post("/{product_id}/delist")
def delist_product(
    product_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        r = svc.delist(db, product_id, user["username"], _is_operator(user))
    except svc.ProductError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(r))


@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        svc.delete_product(db, product_id, user["username"], _is_admin(user))
    except svc.ProductError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap({"deleted": product_id})
