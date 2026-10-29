"""连接器软件分发、CSR 注册、审批和机器身份激活。"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from cryptography.hazmat.primitives import serialization
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_connector_code
from app.models.connector import Connector
from app.schemas.connector import ConnectorApply, ConnectorImport
from app.services.connector_identity import IdentityError, certificate_fingerprint, issue_certificate, parse_csr


class ConnectorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _exists(db: Session, **kw) -> bool:
    return db.execute(select(Connector).filter_by(**kw).where(Connector.deleted_at.is_(None))).first() is not None


def _csr(body: ConnectorApply):
    try:
        return parse_csr(body.csr_pem)
    except IdentityError as exc:
        raise ConnectorError(str(exc), 422) from exc


def apply(db: Session, username: str, body: ConnectorApply) -> Connector:
    csr, csr_fp, key_fp = _csr(body)
    existing = db.scalar(select(Connector).where(Connector.public_key_fingerprint == key_fp))
    if existing and existing.deleted_at is None:
        raise ConnectorError("该连接器公钥已提交注册", 409)
    if existing:
        existing.name = body.name
        existing.org_name = body.org_name
        existing.csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
        existing.csr_fingerprint = csr_fp
        existing.status = "applying"
        existing.tds_code = None
        existing.certificate_pem = None
        existing.certificate_serial = None
        existing.certificate_not_before = None
        existing.certificate_not_after = None
        existing.activated_at = None
        existing.last_seen_at = None
        existing.created_by = username
        existing.deleted_at = None
        db.commit()
        db.refresh(existing)
        return existing
    c = Connector(
        name=body.name,
        org_name=body.org_name,
        csr_pem=body.csr_pem,
        csr_fingerprint=csr_fp,
        public_key_fingerprint=key_fp,
        status="applying",
        created_by=username,
    )
    db.add(c)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConnectorError("该 CSR 或公钥已提交注册", 409) from exc
    db.refresh(c)
    return c


def _assign_tds_code(db: Session) -> str:
    for _ in range(5):
        code = gen_connector_code(settings.tds_default_subject_code, settings.tds_default_region_industry)
        if not _exists(db, tds_code=code):
            return code
    raise ConnectorError("标识码分配失败，请重试", 500)


def _cert_time(cert, name: str):
    aware = getattr(cert, f"{name}_utc", None)
    value = aware if aware is not None else getattr(cert, name)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def approve(db: Session, connector_id: str) -> Connector:
    c = _get_or_404(db, connector_id)
    if c.status != "applying":
        raise ConnectorError(f"当前状态 {c.status} 不可审批", 409)
    csr, _, _ = parse_csr(c.csr_pem)
    c.tds_code = _assign_tds_code(db)
    cert, pem, _, _ = issue_certificate(csr, c.id, c.tds_code, c.org_name)
    c.certificate_pem = pem
    c.certificate_serial = format(cert.serial_number, "x")
    c.certificate_not_before = _cert_time(cert, "not_valid_before")
    c.certificate_not_after = _cert_time(cert, "not_valid_after")
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
    c = apply(db, username, body)
    return approve(db, c.id)


def _get_or_404(db: Session, connector_id: str) -> Connector:
    c = db.get(Connector, connector_id)
    if not c or c.deleted_at is not None:
        raise ConnectorError("连接器不存在", 404)
    return c


def get(db: Session, connector_id: str) -> Connector:
    return _get_or_404(db, connector_id)


def certificate(db: Session, connector_id: str) -> tuple[Connector, str]:
    c = _get_or_404(db, connector_id)
    if c.status not in {"approved", "active"} or not c.certificate_pem:
        raise ConnectorError("连接器尚未审批签发证书", 409)
    from app.services.connector_identity import ca_certificate_pem
    return c, ca_certificate_pem()


def activate(db: Session, connector_id: str, fingerprint: str) -> Connector:
    c = _get_or_404(db, connector_id)
    if not c.certificate_pem:
        raise ConnectorError("连接器尚未签发证书", 409)
    if certificate_fingerprint(c.certificate_pem) != fingerprint.lower():
        raise ConnectorError("本地证书与中心签发证书不一致", 403)
    now = datetime.now(timezone.utc)
    c.status = "active"
    c.activated_at = c.activated_at or now
    c.last_seen_at = now
    db.commit()
    db.refresh(c)
    return c


def list_for(db: Session, username: str, is_admin: bool) -> list[Connector]:
    stmt = select(Connector).where(Connector.deleted_at.is_(None))
    if not is_admin:
        stmt = stmt.where(Connector.created_by == username)
    return list(db.scalars(stmt.order_by(Connector.created_at.desc())))


def soft_delete(db: Session, connector_id: str) -> None:
    c = _get_or_404(db, connector_id)
    c.status = "revoked"
    c.deleted_at = func.now()
    db.commit()


def deployment_instructions(system: str, deployment_platform: str, architecture: str, version: str) -> dict:
    if system != "linux" or architecture != "amd64":
        raise ConnectorError("当前已验证的连接器发布包仅支持 Linux amd64", 422)
    if deployment_platform != "docker-compose":
        raise ConnectorError("当前已验证的部署方式仅支持 Docker Compose", 422)
    image = settings.connector_portal_image
    api = settings.connector_platform_api_public_url
    if deployment_platform == "docker-compose":
        base_url = api.rstrip('/')
        commands = f"""mkdir -p bonfire-connector
cd bonfire-connector
curl -fsSLo docker-compose.yml {base_url}/connectors/downloads/{version}/docker-compose.yml
curl -fsSLo connector-runtime.tar.gz {base_url}/connectors/downloads/{version}/connector-runtime.tar.gz
mkdir -p runtime && tar -xzf connector-runtime.tar.gz -C runtime
CONNECTOR_ID=connector-$(hostname | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | cut -c1-30)
cat > .env <<EOF
COMPOSE_PROJECT_NAME=$CONNECTOR_ID
CONNECTOR_ID=$CONNECTOR_ID
CONNECTOR_IMAGE={image}
SEATUNNEL_IMAGE={settings.connector_seatunnel_image}
PLATFORM_API_BASE={api}
PORTAL_PORT=8100
BONFIRE_EXECUTION_DISPATCH_SECRET=
EOF
chmod 600 .env
docker compose pull
docker compose up -d --wait --wait-timeout 180
curl --noproxy '*' -fsS http://127.0.0.1:8100/health
docker compose ps"""
    return {
        "system": system,
        "deployment_platform": deployment_platform,
        "architecture": architecture,
        "version": version,
        "commands": commands,
        "notes": ["执行通道默认关闭；由部署管理员通过受控渠道将至少 32 字符的随机执行密钥分别配置到中心和受信 Portal 的 .env，下载接口不返回该密钥。", "部署内容包含 Connector Portal 与该连接器独立的 SeaTunnel 实例。", "配置保存在部署目录的 .env 文件中；请限制该文件的读取权限。", "首次启动后在 Portal 本地生成私钥和 CSR。", "Kuscia 等隐私计算引擎需要在连接器注册完成后单独集成。"],
    }


def connector_compose(version: str) -> str:
    """Render a self-contained Docker Compose bundle for one v2 connector.

    Environment variables are deliberately used for all deployment-specific
    values so the downloaded file can be reused for multiple connectors.
    Kuscia is not part of this base bundle; it is installed later by the
    connector's privacy-compute integration flow.
    """
    if not version or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ConnectorError("连接器版本标识无效", 422)
    return f'''services:
  portal:
    image: ${{CONNECTOR_IMAGE:-{settings.connector_portal_image}}}
    container_name: bonfire-${{CONNECTOR_ID:-connector}}-portal
    restart: unless-stopped
    working_dir: /app
    ports:
      - "${{PORTAL_PORT:-8100}}:8100"
    environment:
      PORT: "8100"
      PLATFORM_API_BASE: ${{PLATFORM_API_BASE:?set PLATFORM_API_BASE}}
      PORTAL_DATA_DIR: /state
      PORTAL_HOME: /state
      STORAGE_ROOT: /data
      WEB_DIST: /app/web/dist
      BONFIRE_EXECUTION_DISPATCH_SECRET: ${{BONFIRE_EXECUTION_DISPATCH_SECRET:-}}
      PORTAL_CONTAINER_HOST: host.docker.internal
      SEATUNNEL_API_BASE: http://seatunnel:5801
      SEATUNNEL_SOURCE_ROOT: /connectors/source
      SEATUNNEL_STAGING_ROOT: /var/lib/bonfire/staging
      KUSCIA_STAGING_RELATIVE_ROOT: staging
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - connector-state:/state
      - connector-data:/data
      - connector-staging:/var/lib/bonfire/staging
    depends_on:
      seatunnel:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=2)"]
      interval: 5s
      timeout: 3s
      retries: 24
      start_period: 10s

  seatunnel:
    image: ${{SEATUNNEL_IMAGE:-{settings.connector_seatunnel_image}}}
    container_name: bonfire-${{CONNECTOR_ID:-connector}}-seatunnel
    restart: unless-stopped
    command: ["/opt/seatunnel/bin/seatunnel-cluster.sh"]
    expose:
      - "5801"
    volumes:
      - seatunnel-logs:/opt/seatunnel/logs
      - connector-data:/connectors/source:ro
      - connector-staging:/var/lib/bonfire/staging
      - ./runtime/seatunnel/guava-27-bonfire.jar:/opt/seatunnel/lib/guava-27-bonfire.jar:ro
      - ./runtime/seatunnel/hive-exec-3.1.3.jar:/opt/seatunnel/lib/hive-exec-3.1.3.jar:ro

volumes:
  connector-state:
    name: bonfire-${{CONNECTOR_ID:-connector}}-state
  connector-data:
    name: bonfire-${{CONNECTOR_ID:-connector}}-data
  connector-staging:
    name: bonfire-${{CONNECTOR_ID:-connector}}-staging
  seatunnel-logs:
    name: bonfire-${{CONNECTOR_ID:-connector}}-seatunnel-logs
'''
