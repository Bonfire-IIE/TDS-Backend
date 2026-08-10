"""连接器业务逻辑：申请/审批/驳回/导入 + 部署指引 + 实时状态派生。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_connector_code
from app.integrations.kuscia import KusciaError, get_kuscia_client
from app.models.connector import Connector
from app.schemas.connector import ConnectorApply, ConnectorImport


class ConnectorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _exists(db: Session, **kw) -> bool:
    # 仅在未软删除行中查重（软删后同名 domain/标识码应可再次登记）
    stmt = select(Connector).filter_by(**kw).where(Connector.deleted_at.is_(None))
    return db.execute(stmt).first() is not None


def apply(db: Session, username: str, body: ConnectorApply) -> Connector:
    if _exists(db, kuscia_domain_id=body.kuscia_domain_id):
        raise ConnectorError(f"domain_id '{body.kuscia_domain_id}' 已被占用", 409)
    c = Connector(
        name=body.name,
        org_name=body.org_name,
        kuscia_domain_id=body.kuscia_domain_id,
        status="applying",
        lite_api_endpoint=body.lite_api_endpoint,
        lite_api_port=body.lite_api_port,
        auth_port=body.auth_port, grpc_port=body.grpc_port,
        app_port=body.app_port, data_port=body.data_port,
        created_by=username,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _assign_tds_code(db: Session) -> str:
    for _ in range(5):
        code = gen_connector_code(settings.tds_default_subject_code, settings.tds_default_region_industry)
        if not _exists(db, tds_code=code):
            return code
    raise ConnectorError("标识码分配失败，请重试", 500)


def approve(db: Session, connector_id: str) -> Connector:
    c = _get_or_404(db, connector_id)
    if c.status != "applying":
        raise ConnectorError(f"当前状态 {c.status} 不可审批", 409)
    # 建 Kuscia Domain（真集成），分配 32 位标识码
    try:
        get_kuscia_client().create_domain(c.kuscia_domain_id)
    except KusciaError as e:
        raise ConnectorError(f"创建 Kuscia Domain 失败: {e}", 502) from e
    c.tds_code = _assign_tds_code(db)
    c.status = "approved"
    db.commit()
    db.refresh(c)
    return c


def reject(db: Session, connector_id: str) -> Connector:
    c = _get_or_404(db, connector_id)
    if c.status != "applying":
        raise ConnectorError(f"当前状态 {c.status} 不可驳回", 409)
    c.status = "rejected"
    db.commit()
    db.refresh(c)
    return c


def import_existing(db: Session, username: str, body: ConnectorImport) -> Connector:
    """把已存在的 Kuscia Domain（如 alice/bob）登记为已批准连接器。"""
    if _exists(db, kuscia_domain_id=body.kuscia_domain_id):
        raise ConnectorError(f"domain '{body.kuscia_domain_id}' 已登记", 409)
    try:
        data = get_kuscia_client().query_domain(body.kuscia_domain_id).get("data", {})
        if not data.get("domain_id"):
            raise ConnectorError(f"Kuscia 中不存在 domain '{body.kuscia_domain_id}'", 404)
    except KusciaError as e:
        raise ConnectorError(f"查询 Kuscia Domain 失败: {e}", 502) from e
    c = Connector(
        name=body.name or body.kuscia_domain_id,
        org_name=body.org_name,
        kuscia_domain_id=body.kuscia_domain_id,
        tds_code=_assign_tds_code(db),
        status="approved",
        lite_api_endpoint=body.lite_api_endpoint,
        lite_api_port=body.lite_api_port,
        auth_port=body.auth_port, grpc_port=body.grpc_port,
        app_port=body.app_port, data_port=body.data_port,
        created_by=username,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _get_or_404(db: Session, connector_id: str) -> Connector:
    c = db.get(Connector, connector_id)
    if not c or c.deleted_at is not None:
        raise ConnectorError("连接器不存在", 404)
    return c


def get(db: Session, connector_id: str) -> Connector:
    return _get_or_404(db, connector_id)


def report_node_info(db: Session, connector_id: str, username: str, is_admin: bool, body) -> Connector:
    """连接器门户部署完 Lite 后回传节点物理信息；仅更新提供的字段。属主或 admin 可报。"""
    c = _get_or_404(db, connector_id)
    if c.created_by != username and not is_admin:
        raise ConnectorError("无权回传该连接器节点信息", 403)
    for field in ("endpoint", "lite_api_endpoint", "lite_api_port",
                  "auth_port", "grpc_port", "app_port", "data_port"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(c, field, val)
    db.commit()
    db.refresh(c)
    return c


def list_for(db: Session, username: str, is_admin: bool) -> list[Connector]:
    stmt = select(Connector).where(Connector.deleted_at.is_(None))
    if not is_admin:
        stmt = stmt.where(Connector.created_by == username)
    stmt = stmt.order_by(Connector.created_at.desc())
    return list(db.execute(stmt).scalars())


def soft_delete(db: Session, connector_id: str) -> None:
    c = _get_or_404(db, connector_id)
    c.deleted_at = func.now()
    db.commit()


def display_status(c: Connector) -> str:
    """派生展示态：approved 连接器按 Kuscia 实时在线情况显示 online/offline。"""
    if c.status != "approved":
        return c.status
    try:
        return "online" if get_kuscia_client().domain_online(c.kuscia_domain_id) else "offline"
    except KusciaError:
        return "offline"


def _deploy_commands(c: Connector, token: str | None) -> str:
    img = settings.kuscia_image
    master = settings.kuscia_master_deploy_endpoint
    tok = token or "<部署令牌不可用：请确认该连接器已审批且令牌未被使用>"
    domain_id = c.kuscia_domain_id
    auth, api = c.auth_port or 1080, c.lite_api_port or 8082
    grpc, app, data = c.grpc_port or 8083, c.app_port or 80, c.data_port or 9091
    return f"""# 在【连接器主机】上执行（需能访问 master {master}）
export KUSCIA_IMAGE={img}
docker pull $KUSCIA_IMAGE
docker run --rm $KUSCIA_IMAGE cat /home/kuscia/scripts/deploy/kuscia.sh > kuscia.sh && chmod +x kuscia.sh
docker run -it --rm $KUSCIA_IMAGE kuscia init --mode lite --domain {domain_id} \\
  --master-endpoint "{master}" --lite-deploy-token "{tok}" > lite_{domain_id}.yaml
# 同机多节点需错开端口(-p 认证 -k KusciaAPI-HTTP -g GRPC -q 应用 -x metrics)
./kuscia.sh start -c lite_{domain_id}.yaml -p {auth} -k {api} -g {grpc} -q {app} -x {data}"""


def deploy_info(c: Connector) -> dict:
    if c.status != "approved":
        raise ConnectorError("连接器未审批，无部署信息", 409)
    token = None
    try:
        token = get_kuscia_client().get_deploy_token(c.kuscia_domain_id)
    except KusciaError:
        pass
    return {
        "kuscia_domain_id": c.kuscia_domain_id,
        "deploy_token": token,
        "master_endpoint": settings.kuscia_master_deploy_endpoint,
        "kuscia_image": settings.kuscia_image,
        "commands": _deploy_commands(c, token),
    }


def deploy_script(c: Connector) -> str:
    info = deploy_info(c)
    return "#!/bin/bash\nset -euo pipefail\n" + info["commands"] + "\n"
