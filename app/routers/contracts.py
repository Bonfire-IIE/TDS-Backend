"""contracts 模块：数字合约发起、磋商、签署、备案、终止。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.contract import DigitalContract
from app.schemas.contract import ContractOut, ContractRequest, ProposeRequest
from app.services import contract as svc

router = APIRouter(prefix="/contracts", tags=["contracts"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _is_admin(user: dict) -> bool:
    return bool({"operator", "supervisor"} & set(user.get("roles", [])))


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(c: DigitalContract) -> ContractOut:
    return ContractOut.model_validate(c)


@router.post("/products/{product_id}/request", status_code=201)
def request_contract(
    product_id: str,
    body: ContractRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.request(db, product_id, user["username"], _is_admin(user), body)
    except svc.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.get("")
def list_contracts(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_contracts(db, user["username"], _is_operator(user))
    return _wrap([_out(c) for c in items])


@router.get("/{contract_id}")
def get_contract(
    contract_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        c = svc.get(db, contract_id, user["username"], _is_operator(user))
    except svc.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


def _action(fn, contract_id, user, db, *args):
    try:
        c = fn(db, contract_id, user["username"], _is_operator(user), *args)
    except svc.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(c))


@router.post("/{contract_id}/propose")
def propose(
    contract_id: str,
    body: ProposeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _action(svc.propose, contract_id, user, db, body)


@router.post("/{contract_id}/sign")
def sign(
    contract_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _action(svc.sign, contract_id, user, db)


@router.post("/{contract_id}/file")
def file_contract(
    contract_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _action(svc.file, contract_id, user, db)


@router.post("/{contract_id}/terminate")
def terminate(
    contract_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _action(svc.terminate, contract_id, user, db)


@router.post("/{contract_id}/reject")
def reject(
    contract_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return _action(svc.reject, contract_id, user, db)
