"""Administration APIs for importing externally deployed Kuscia Masters."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from datetime import datetime, timezone
from pathlib import Path
import os, tempfile
from app.core.config import settings
from app.integrations.kuscia import KusciaClient, KusciaError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import httpx

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
        scheme=body.scheme,
        deploy_endpoint=body.deploy_endpoint,
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

@router.post("/{master_id}/credentials")
async def upload_credentials(master_id: str, ca: UploadFile = File(...), cert: UploadFile = File(...), key: UploadFile = File(...), token: UploadFile = File(...), user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    master = _get_or_404(db, master_id)
    root = Path(settings.kuscia_credential_root)
    if not root: raise HTTPException(500, "未配置 KUSCIA_CREDENTIAL_ROOT")
    target = root / master.id
    target.mkdir(parents=True, exist_ok=True); os.chmod(target, 0o700)
    for name, upload in (("ca.crt", ca), ("kusciaapi-server.crt", cert), ("kusciaapi-server.key", key), ("token", token)):
        data = await upload.read()
        if not data or len(data) > 4 * 1024 * 1024: raise HTTPException(422, f"非法凭据文件: {name}")
        path = target / name; path.write_bytes(data); os.chmod(path, 0o600)
    master.credential_ref = f"file:{target}"; master.status = "credentials_uploaded"; master.last_error = None
    db.commit(); db.refresh(master)
    return _wrap(KusciaMasterOut.model_validate(master))

@router.post("/{master_id}/test")
def test_master(master_id: str, user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    master = _get_or_404(db, master_id)
    if not master.credential_ref or not master.credential_ref.startswith("file:"):
        raise HTTPException(409, "尚未上传 Kuscia Master 凭据")
    endpoint = f"{master.scheme}://{master.deployment_ip}:{master.api_port}"
    try:
        KusciaClient(endpoint=endpoint, cert_dir=master.credential_ref[5:]).query_domain("kuscia-system")
        master.status = "connected"; master.last_error = None
        result = {"ok": True}
    except Exception as exc:
        master.status = "error"; master.last_error = str(exc)[:1000]
        result = {"ok": False, "message": master.last_error}
    master.last_checked_at = datetime.now(timezone.utc); db.commit()
    return _wrap(result)

@router.post("/{master_id}/probe")
def probe_master(master_id: str, _user: dict = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    master = _get_or_404(db, master_id)
    endpoint = f"{master.scheme}://{master.deployment_ip}:{master.api_port}"
    try:
        r = httpx.get(f"{endpoint}/api/v1/health", timeout=5, verify=False)
        ok = r.status_code < 500
        result = {"ok": ok, "message": "地址可达" if ok else f"服务返回 HTTP {r.status_code}"}
        master.status = "reachable" if ok else "error"
        master.last_error = None if ok else result["message"]
    except Exception as exc:
        result = {"ok": False, "message": f"地址不可达：{str(exc)[:500]}"}
        master.status = "error"; master.last_error = result["message"]
    master.last_checked_at = datetime.now(timezone.utc); db.commit()
    return _wrap(result)


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
