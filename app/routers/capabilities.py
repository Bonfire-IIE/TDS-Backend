from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.capability import ConnectorCapability, PrivacyApplication, PrivacyApplicationBinding
from app.models.connector import Connector
from app.schemas.capability import CapabilityCreate, CapabilityOut, ApplicationOut, PrivacyComputeProvision, ApplicationCreate

router = APIRouter(prefix="/capabilities", tags=["capabilities"])

@router.post("/applications", status_code=201)
def register_application(body: ApplicationCreate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not ({"operator", "supervisor"} & set(user.get("roles", []))):
        raise HTTPException(403, "只有运营方可以注册 AppImage")
    row = db.get(PrivacyApplication, body.code)
    if row and row.status == "published":
        raise HTTPException(409, "AppImage 应用编码已存在")
    if not row:
        row = PrivacyApplication(code=body.code, created_by=user["username"])
        db.add(row)
    for key in ("name", "description", "execution_env_code", "version", "input_schema", "output_schema", "extension_schema"):
        setattr(row, key, getattr(body, key))
    row.status = "published"
    binding = db.scalar(select(PrivacyApplicationBinding).where(
        PrivacyApplicationBinding.application_code == body.code,
        PrivacyApplicationBinding.system_type == "privacy-compute",
        PrivacyApplicationBinding.system_application_ref == body.implementation_ref,
    ))
    if not binding:
        binding = PrivacyApplicationBinding(application_code=body.code, system_type="privacy-compute", system_application_ref=body.implementation_ref)
        db.add(binding)
    binding.system_application_version = body.implementation_version
    binding.capability_requirements = body.capability_requirements
    binding.adapter_version = body.adapter_version
    binding.implementation_metadata = body.implementation_metadata
    db.commit()
    return {"code": 0, "message": "ok", "data": ApplicationOut.model_validate(row)}


@router.get("/applications")
def applications(_: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(PrivacyApplication).where(PrivacyApplication.status == "published").order_by(PrivacyApplication.code)).all()
    data = []
    for row in rows:
        bindings = db.scalars(select(PrivacyApplicationBinding).where(
            PrivacyApplicationBinding.application_code == row.code,
            PrivacyApplicationBinding.status == "published",
        )).all()
        item = ApplicationOut.model_validate(row).model_dump()
        item["execution_bindings"] = [{
            "system_type": binding.system_type,
            "implementation_ref": binding.system_application_ref,
            "implementation_version": binding.system_application_version,
            "capability_requirements": binding.capability_requirements or [],
            "adapter_version": binding.adapter_version,
        } for binding in bindings]
        data.append(item)
    return {"code": 0, "message": "ok", "data": data}


@router.get("/connectors/{connector_id}")
def list_connector_capabilities(connector_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    connector = db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(404, "连接器不存在")
    if connector.created_by != user["username"] and not ({"operator", "supervisor"} & set(user.get("roles", []))):
        raise HTTPException(403, "无权查看该连接器能力")
    rows = db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id == connector_id).order_by(ConnectorCapability.capability_code)).all()
    return {"code": 0, "message": "ok", "data": [CapabilityOut.model_validate(x) for x in rows]}


@router.post("/connectors/{connector_id}", status_code=201)
def declare_connector_capability(connector_id: str, body: CapabilityCreate, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    connector = db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(404, "连接器不存在")
    if connector.created_by != user["username"] and "operator" not in user.get("roles", []):
        raise HTTPException(403, "只能登记自己拥有的连接器能力")
    row = db.scalar(select(ConnectorCapability).where(ConnectorCapability.connector_id == connector_id, ConnectorCapability.capability_code == body.capability_code))
    if row:
        row.capability_version = body.capability_version
        row.adapter_type = body.adapter_type
        row.implementation_ref = body.implementation_ref
        row.evidence = body.evidence
        row.status = "declared"
    else:
        row = ConnectorCapability(
            connector_id=connector_id,
            capability_code=body.capability_code,
            capability_version=body.capability_version,
            adapter_type=body.adapter_type,
            implementation_ref=body.implementation_ref,
            evidence=body.evidence,
            status="declared",
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"code": 0, "message": "ok", "data": CapabilityOut.model_validate(row)}


@router.post("/connectors/{connector_id}/{capability_code}/verify")
def verify_connector_capability(connector_id: str, capability_code: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    connector = db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(404, "连接器不存在")
    if connector.created_by != user["username"] and not ({"operator", "supervisor"} & set(user.get("roles", []))):
        raise HTTPException(403, "无权验证该连接器能力")
    row = db.scalar(select(ConnectorCapability).where(ConnectorCapability.connector_id == connector_id, ConnectorCapability.capability_code == capability_code))
    if not row:
        raise HTTPException(404, "连接器尚未声明该能力")
    if not row.adapter_type or not row.implementation_ref:
        row.status = "unavailable"
        row.evidence = {"reason": "未绑定隐私保护计算 adapter 实例"}
        db.commit()
        return {"code": 0, "message": "ok", "data": {"available": False, "capability": capability_code, "reason": "未绑定隐私保护计算 adapter 实例"}}
    # A local engine is probed by the connector portal.  The portal may pass
    # that signed/recorded probe as evidence; this keeps verification usable
    # for P2P autonomy nodes that have no center Master endpoint.
    local_probe = (row.evidence or {}).get("local_probe")
    if isinstance(local_probe, dict) and local_probe.get("available") is True:
        result = {"available": True, "capability": capability_code, "source": "connector-portal"}
    else:
        result = {"available": False, "capability": capability_code, "reason": "连接器未提交本地执行网关探活结果"}
    row.status = "verified" if result.get("available") else "unavailable"
    row.evidence = {**(row.evidence or {}), "verification": result}
    row.verified_at = datetime.now(timezone.utc) if result.get("available") else None
    db.commit()
    return {"code": 0, "message": "ok", "data": result}
@router.post("/connectors/{connector_id}/privacy-compute/provision")
def provision_privacy_compute(connector_id: str, body: PrivacyComputeProvision, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    connector = db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(404, "连接器不存在")
    if connector.created_by != user["username"]:
        raise HTTPException(403, "只能为自己的连接器部署能力")
    if connector.status != "active":
        raise HTTPException(409, "连接器身份尚未激活")
    # Domain names and enrollment credentials are allocated by the center.
    # Never issue a token for an arbitrary user-supplied domain.
    ref = "pc-" + connector.id.replace("-", "")[:24]
    from app.integrations.kuscia import get_kuscia_client, get_kuscia_master_deploy_endpoint, KusciaError
    client = get_kuscia_client()
    try:
        client.create_domain(ref)
        import time
        token = None
        for _ in range(10):
            token = client.get_deploy_token(ref)
            if token:
                break
            time.sleep(0.5)
        if not token:
            raise HTTPException(409, "Lite 已接入或暂无部署令牌，请由中心管理员处理重新接入")
        return {"code": 0, "message": "ok", "data": {
            "adapter_type": "privacy-compute", "implementation_ref": ref,
            "mode": "master-lite", "node_type": "lite",
            "master_endpoint": get_kuscia_master_deploy_endpoint(),
            "deploy_token": token, "engine_image": settings.connector_kuscia_image,
        }}
    except KusciaError as exc:
        raise HTTPException(503, "中心 Kuscia Master 暂不可用") from exc
    finally:
        client.close()
