"""jobs 模块：隐私计算作业发起、检索、状态同步。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.job import Job
from app.schemas.job import JobCreate, JobOut
from app.services import job as svc

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _is_operator(user: dict) -> bool:
    return "operator" in user.get("roles", [])


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _out(j: Job) -> JobOut:
    return JobOut.model_validate(j)


@router.post("", status_code=201)
def create_job(
    body: JobCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        j = svc.create_job(db, user["username"], _is_operator(user), body)
    except svc.JobError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(j))


@router.get("")
def list_jobs(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = svc.list_jobs(db, user["username"], _is_operator(user))
    return _wrap([_out(j) for j in items])


@router.get("/{job_id}")
def get_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询作业详情，并实时同步一次 Kuscia 状态。"""
    try:
        j = svc.get(db, job_id, user["username"], _is_operator(user), refresh=True)
    except svc.JobError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(j))


@router.post("/{job_id}/refresh")
def refresh_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """手动触发一次 Kuscia 状态同步。"""
    try:
        j = svc.get(db, job_id, user["username"], _is_operator(user), refresh=True)
    except svc.JobError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return _wrap(_out(j))
