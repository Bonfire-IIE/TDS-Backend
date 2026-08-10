"""Administration APIs for importing externally deployed Kuscia Masters."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_roles
from app.models.kuscia_master import KusciaMaster
from app.schemas.kuscia_master import (
    KusciaMasterImport,
    KusciaMasterOut,
    KusciaMasterUpdate,
    normalized_ip,
)

router = APIRouter(prefix="/kuscia-masters", tags=["kuscia-masters"])
admin_user = require_roles("operator", "supervisor")


def _wrap(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _get_or_404(db: Session, master_id: str) -> KusciaMaster:
    master = db.get(KusciaMaster, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Kuscia Master 节点不存在")
    return master


@router.get("")
def list_masters(
    _user: dict = Depends(admin_user), db: Session = Depends(get_db)
) -> dict:
    masters = db.scalars(
        select(KusciaMaster).order_by(KusciaMaster.created_at.desc())
    ).all()
    return _wrap([KusciaMasterOut.model_validate(item) for item in masters])


@router.post("", status_code=201)
def import_master(
    body: KusciaMasterImport,
    user: dict = Depends(admin_user),
    db: Session = Depends(get_db),
) -> dict:
    master = KusciaMaster(
        name=body.name.strip(),
        deployment_ip=normalized_ip(body.deployment_ip),
        api_port=body.api_port,
        created_by=user["username"],
    )
    db.add(master)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该 Kuscia Master 节点已导入") from exc
    db.refresh(master)
    return _wrap(KusciaMasterOut.model_validate(master))


@router.patch("/{master_id}")
def update_master(
    master_id: str,
    body: KusciaMasterUpdate,
    _user: dict = Depends(admin_user),
    db: Session = Depends(get_db),
) -> dict:
    master = _get_or_404(db, master_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    if "deployment_ip" in changes:
        changes["deployment_ip"] = normalized_ip(changes["deployment_ip"])
    for key, value in changes.items():
        setattr(master, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该 Kuscia Master 节点已导入") from exc
    db.refresh(master)
    return _wrap(KusciaMasterOut.model_validate(master))


@router.delete("/{master_id}")
def delete_master(
    master_id: str,
    _user: dict = Depends(admin_user),
    db: Session = Depends(get_db),
) -> dict:
    master = _get_or_404(db, master_id)
    db.delete(master)
    db.commit()
    return _wrap(None)
