from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.ucon import UconCheckRequest, UconCheckOut
from app.services import ucon
router = APIRouter(prefix="/ucon", tags=["ucon"])
@router.post("/contracts/{contract_id}/checks", response_model=dict)
def create_check(contract_id: str, body: UconCheckRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try: row = ucon.record(db, contract_id, body.stage, user["username"], body.checks, body.evidence, body.project_id, body.job_id); db.commit(); db.refresh(row)
    except ValueError as exc: raise HTTPException(400, str(exc))
    return {"code": 0, "message": "ok", "data": UconCheckOut.model_validate(row)}
@router.get("/contracts/{contract_id}/checks", response_model=dict)
def list_checks(contract_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"code": 0, "message": "ok", "data": [UconCheckOut.model_validate(x) for x in ucon.list_checks(db, contract_id)]}
