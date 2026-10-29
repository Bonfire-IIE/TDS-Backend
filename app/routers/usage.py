"""使用控制决策记录查询。准入决策由作业接口内部强制执行。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.connector import Connector
from app.services.standard_contract import info as contract_info, execution_nodes
from app.models.capability import PrivacyApplication
from app.models.contract import DigitalContract
from app.models.usage import UsageRecord
from app.schemas.usage import UsagePreflightOut, UsageRecordOut
from app.services import usage as svc

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/records")
def list_records(
    contract_id: str | None = None,
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    stmt = select(UsageRecord).order_by(UsageRecord.created_at.desc())
    if contract_id:
        stmt = stmt.where(UsageRecord.contract_id == contract_id)
    if "operator" not in user.get("roles", []):
        owned = select(Connector.id).where(Connector.created_by == user["username"])
        stmt = stmt.where(UsageRecord.connector_id.in_(owned))
    records = db.execute(stmt).scalars().all()
    data = [UsageRecordOut.model_validate(record) for record in records]
    return {"code": 0, "message": "ok", "data": data}


@router.get("/preflight", response_model=None)
def preflight(
    contract_id: str, application_code: str, action: str = "process",
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    contract = db.get(DigitalContract, contract_id)
    if not contract:
        raise HTTPException(404, "合约不存在")
    if contract_info(contract.document)["contractStatus"] != "filed":
        raise HTTPException(409, "合约未备案")
    node_id = execution_nodes(contract.document)["consumerNodeId"]
    connector = db.scalar(select(Connector).where((Connector.tds_code == node_id) | (Connector.id == node_id)))
    is_operator = "operator" in user.get("roles", [])
    if not connector or (not is_operator and connector.created_by != user["username"]):
        raise HTTPException(403, "仅用数方或运营方可预检")
    app = db.execute(select(PrivacyApplication).where(PrivacyApplication.code == application_code)).scalar_one_or_none()
    if not app or app.status != "published":
        raise HTTPException(404, "应用能力不存在或已下架")
    try:
        result = svc.preflight(
            db, contract, user["username"], connector.id,
            action, app.execution_env_code, application_code,
        )
    except svc.UsageError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return {"code": 0, "message": "ok", "data": UsagePreflightOut(**result)}
