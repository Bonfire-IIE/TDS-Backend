"""Administration APIs for importing externally deployed Kuscia Masters."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from datetime import datetime, timezone
from pathlib import Path
import os
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
    KusciaMasterDeployGuide,
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


def _primary_master(db: Session) -> KusciaMaster | None:
    return db.scalars(
        select(KusciaMaster)
        .where(KusciaMaster.enabled.is_(True))
        .order_by(KusciaMaster.created_at.desc())
    ).first()


@router.get("/onboarding/state")
def onboarding_state(
    _user: dict = Depends(admin_user), db: Session = Depends(get_db)
) -> dict:
    """引导页只读状态；数据库记录是引导页和中心平台共同的唯一事实来源。"""
    master = _primary_master(db)
    if master is None:
        return _wrap({"configured": False, "completed": False, "master": None})
    completed = master.status in {"credentials_uploaded", "connected"}
    return _wrap({
        "configured": True,
        "completed": completed,
        "master": KusciaMasterOut.model_validate(master),
    })


@router.post("/onboarding/deploy-script")
def onboarding_deploy_script(
    body: KusciaMasterDeployGuide,
    _user: dict = Depends(admin_user),
) -> dict:
    """生成由运营方在 Master 主机执行的脚本；平台本身不远程执行命令。"""
    image = (body.kuscia_image or settings.kuscia_image).strip()
    if not image:
        raise HTTPException(status_code=422, detail="未配置 Kuscia 镜像，请填写镜像地址")
    ip = normalized_ip(body.deployment_ip)
    deploy_endpoint = f"https://{ip}:{body.auth_port}"
    api_endpoint = f"https://{ip}:{body.api_port}"
    commands = f'''#!/bin/bash
set -euo pipefail

export KUSCIA_IMAGE="{image}"
export KUSCIA_DOMAIN_ID="{body.domain_id}"

docker pull "$KUSCIA_IMAGE"
docker run --rm "$KUSCIA_IMAGE" cat /home/kuscia/scripts/deploy/kuscia.sh > kuscia.sh
chmod u+x kuscia.sh
docker run --rm "$KUSCIA_IMAGE" kuscia init --mode master --domain "$KUSCIA_DOMAIN_ID" > kuscia_master.yaml
./kuscia.sh start -c kuscia_master.yaml \
  -p {body.auth_port} -k {body.api_port} -g {body.grpc_port} \
  -q {body.app_port} -x {body.metrics_port}

# 导出中心平台访问 KusciaAPI 所需的四个凭据文件
MASTER_CONTAINER="$(docker ps --format '{{{{.Names}}}}' | grep 'kuscia-master' | head -n1)"
test -n "$MASTER_CONTAINER"
mkdir -p ./kuscia-master-certs
docker cp "$MASTER_CONTAINER":/home/kuscia/var/certs/. ./kuscia-master-certs/
ls -1 ./kuscia-master-certs
'''
    return _wrap({
        "commands": commands,
        "api_endpoint": api_endpoint,
        "deploy_endpoint": deploy_endpoint,
        "kuscia_image": image,
    })


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
        domain_id=body.domain_id,
        deployment_ip=normalized_ip(body.deployment_ip),
        auth_port=body.auth_port,
        api_port=body.api_port,
        grpc_port=body.grpc_port,
        app_port=body.app_port,
        metrics_port=body.metrics_port,
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
    if not settings.kuscia_credential_root:
        raise HTTPException(500, "未配置 KUSCIA_CREDENTIAL_ROOT")
    root = Path(settings.kuscia_credential_root)
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
        KusciaClient(endpoint=endpoint, cert_dir=master.credential_ref[5:], domain_id=master.domain_id).ping()
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
    credential_dir = None
    if master.credential_ref and master.credential_ref.startswith("file:"):
        credential_dir = Path(master.credential_ref[5:])
    db.delete(master)
    db.commit()
    # 数据库提交成功后，仅清理该 Master 在平台凭据根目录下的上传副本。
    if credential_dir and settings.kuscia_credential_root:
        root = Path(settings.kuscia_credential_root).resolve()
        target = credential_dir.resolve()
        if target.parent == root and target.name == master_id and target.is_dir():
            for item in target.iterdir():
                if item.is_file() or item.is_symlink():
                    item.unlink()
            target.rmdir()
    return _wrap(None)
