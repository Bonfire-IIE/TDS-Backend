"""应用能力(AppImage)业务逻辑：内置纳管(懒加载种子) / 注册自定义 / 检索 / 下架。

MVP：先纳管 Kuscia 内置 SecretFlow 镜像（scope=builtin），
自定义镜像走 register 创建到 Kuscia 并落库（scope=custom）。
"""
from __future__ import annotations

import re
import uuid
import yaml

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.kuscia import KusciaError, get_kuscia_client
from app.models.appimage import AppImage
from app.schemas.appimage import AppImageCreate

# Kuscia 内置镜像 -> (平台能力类别)。首次 list 时懒加载纳管。
BUILTIN_APPIMAGES = {
    "secretflow-image": "psi",           # SecretFlow 引擎，PSI 等用它
    "secretflow-nsjail-image": "general",
}


class AppImageError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_kuscia_fields(value):
    """把 CR YAML 的 camelCase 递归转换为 KusciaAPI 使用的 snake_case。"""
    if isinstance(value, list):
        return [normalize_kuscia_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): normalize_kuscia_fields(item)
            for key, item in value.items()
        }
    return value


def parse_config(content: str, kind: str) -> dict:
    """Parse JSON/YAML and expose the exact structure sent to KusciaAPI."""
    try:
        documents = [item for item in yaml.safe_load_all(content) if item is not None]
    except yaml.YAMLError as e:
        raise AppImageError(f"JSON/YAML 解析失败: {e}", 400) from e
    if kind != "appimage" and len(documents) != 1:
        raise AppImageError("模板必须只包含一个 JSON/YAML 文档", 400)

    if kind == "deploy_templates":
        value = documents[0] if documents else None
        if not isinstance(value, list) or not value:
            raise AppImageError("部署模板必须是非空数组", 400)
        return {"deploy_templates": normalize_kuscia_fields(value)}
    if kind == "config_templates":
        value = documents[0] if documents else None
        if not isinstance(value, dict):
            raise AppImageError("配置模板必须是对象", 400)
        return {"config_templates": value}

    resource = next(
        (item for item in documents if isinstance(item, dict) and item.get("kind") == "AppImage"),
        documents[0] if len(documents) == 1 and isinstance(documents[0], dict) else None,
    )
    if not resource:
        raise AppImageError("文件中未找到 AppImage 资源", 400)
    spec = resource.get("spec", resource)
    deploy = spec.get("deployTemplates", spec.get("deploy_templates"))
    config = spec.get("configTemplates", spec.get("config_templates"))
    if not isinstance(deploy, list) or not deploy:
        raise AppImageError("AppImage 缺少 spec.deployTemplates 数组", 400)
    if config is not None and not isinstance(config, dict):
        raise AppImageError("spec.configTemplates 必须是对象", 400)
    image = spec.get("image") or {}
    result = {
        "name": (resource.get("metadata") or {}).get("name", resource.get("name")),
        "image": {"name": image.get("name"), "tag": image.get("tag")},
        "deploy_templates": normalize_kuscia_fields(deploy),
    }
    if config is not None:
        result["config_templates"] = config
    return result


# ---- 内置能力懒加载种子 ----
def seed_builtin(db: Session) -> None:
    """首次调用且库中无任何记录时，把 Kuscia 内置镜像读回登记为 builtin。

    仅读取 Kuscia 已有结构（query_appimage），不重复创建 Kuscia 侧。
    读取失败静默跳过（Kuscia 不可用时不阻断列表）。
    """
    if db.execute(select(AppImage).limit(1)).first():
        return
    client = get_kuscia_client()
    added = False
    for name, capability in BUILTIN_APPIMAGES.items():
        try:
            data = client.query_appimage(name)
        except KusciaError:
            continue
        if not data:
            continue
        image = data.get("image", {}) or {}
        row = AppImage(
            name=data.get("name", name),
            display_name=data.get("name", name),
            description="Kuscia 内置应用能力",
            capability=capability,
            image_name=image.get("name", ""),
            image_tag=image.get("tag", ""),
            deploy_templates=data.get("deploy_templates"),
            config_templates=data.get("config_templates"),
            status="registered",
            scope="builtin",
            created_by="system",
        )
        db.add(row)
        added = True
    if added:
        db.commit()


# ---- 注册自定义应用能力 ----
def register(db: Session, username: str, is_operator: bool, body: AppImageCreate) -> AppImage:
    if not body.deploy_templates:
        raise AppImageError("deploy_templates 不能为空", 400)
    ports={direction:{p.get("name") for p in ((body.io_schema or {}).get(direction) or []) if isinstance(p,dict)} for direction in ("inputs","outputs")}
    if any(None in names or len(names)!=len((body.io_schema or {}).get(direction) or []) for direction,names in ports.items()):
        raise AppImageError("I/O 端口必须有唯一的 name",400)
    if ports["inputs"] and body.task_input_template is None:
        raise AppImageError("声明输入端口的应用必须提供 task_input_template",400)
    def scan(value):
        if isinstance(value,dict):
            for child in value.values(): scan(child)
        elif isinstance(value,list):
            for child in value: scan(child)
        elif isinstance(value,str):
            for path in re.findall(r"\{\{\s*([^{}]+?)\s*\}\}",value):
                parts=path.strip().split(".")
                if len(parts)>1 and parts[0] in ports and parts[1] not in ports[parts[0]]:
                    raise AppImageError(f"task_input_template 引用了未声明的{parts[0]}端口: {parts[1]}",400)
                if any(x.lower() in {"secret","password","token","private_key","access_key_secret","ak","sk"} for x in parts):
                    raise AppImageError(f"task_input_template 不允许引用秘密字段: {path}",400)
    scan(body.task_input_template)

    # 生成 Kuscia AppImage name（集群唯一）
    kuscia_name = body.name or "app-" + uuid.uuid4().hex[:12]
    existing = db.execute(select(AppImage).where(AppImage.name == kuscia_name)).scalar_one_or_none()
    if existing:
        raise AppImageError(f"AppImage {kuscia_name} 已在平台登记", 409)

    # Kuscia API 使用 snake_case；同时兼容从 CR YAML 复制来的 camelCase 字段。
    deploy_templates = normalize_kuscia_fields(body.deploy_templates)
    # config_templates keys are filenames and must not be treated as API field names.
    config_templates = body.config_templates or None
    if body.registry_source == "platform":
        repository = body.image_name.strip().strip("/")
        prefix = settings.platform_registry_project + "/"
        if repository.startswith(prefix):
            repository = repository[len(prefix):]
        if not repository or "://" in repository or repository.startswith(settings.platform_registry):
            raise AppImageError("平台镜像名称应为项目内仓库路径，如 psi-demo", 400)
        image_name = f"{settings.platform_registry}/{settings.platform_registry_project}/{repository}"
        registry = settings.platform_registry
    else:
        image_name = body.image_name.strip()
        registry = body.registry or (image_name.split("/", 1)[0] if "/" in image_name else "docker.io")
    try:
        get_kuscia_client().create_appimage(
            name=kuscia_name,
            image_name=image_name,
            image_tag=body.image_tag,
            deploy_templates=deploy_templates,
            config_templates=config_templates,
        )
    except KusciaError as e:
        # YAML 可能已先通过 kubectl/KusciaAPI 创建；校验镜像一致后纳管。
        if "exist" not in str(e).lower():
            raise AppImageError(f"创建 Kuscia AppImage 失败: {e}", 502) from e
        remote = get_kuscia_client().query_appimage(kuscia_name)
        remote_image = remote.get("image", {}) or {}
        if remote_image.get("name") != image_name or remote_image.get("tag") != body.image_tag:
            raise AppImageError(f"Kuscia 中已存在同名 AppImage {kuscia_name}，但镜像不一致", 409)

    row = AppImage(
        name=kuscia_name,
        display_name=body.display_name,
        description=body.description,
        capability=body.capability,
        operations=body.operations or ["process"],
        uc_capabilities=body.uc_capabilities or [],
        image_name=image_name,
        image_tag=body.image_tag,
        registry_source=body.registry_source,
        registry=registry,
        deploy_templates=deploy_templates,
        config_templates=config_templates,
        job_template=body.job_template,
        io_schema=body.io_schema,
        party_schema=body.party_schema,
        parameter_schema=body.parameter_schema,
        ui_schema=body.ui_schema,
        task_input_template=body.task_input_template,
        status="registered",
        scope="custom",
        created_by=username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---- 检索 ----
def list_appimages(db: Session, username: str, is_operator: bool) -> list[AppImage]:
    seed_builtin(db)
    stmt = select(AppImage).order_by(AppImage.created_at.desc())
    # 可见性：已登记对所有人可见；下架的仅属主/运营方可见
    if not is_operator:
        stmt = stmt.where(
            or_(AppImage.status == "registered", AppImage.created_by == username)
        )
    return list(db.execute(stmt).scalars())


def get(db: Session, appimage_id: str) -> AppImage:
    row = db.get(AppImage, appimage_id)
    if not row:
        raise AppImageError("应用能力不存在", 404)
    return row


def delist(db: Session, appimage_id: str, username: str, is_operator: bool) -> AppImage:
    row = get(db, appimage_id)
    # 内置能力受保护，不可下架
    if row.scope == "builtin":
        raise AppImageError("内置应用能力受保护，不可下架", 403)
    if not is_operator and row.created_by != username:
        raise AppImageError("无权操作", 403)
    row.status = "delisted"
    db.commit()
    db.refresh(row)
    return row


def update(db: Session, appimage_id: str, username: str, is_operator: bool, body: AppImageCreate) -> AppImage:
    row = get(db, appimage_id)
    if row.scope == "builtin":
        raise AppImageError("内置应用能力受保护，不可修改", 403)
    if not is_operator and row.created_by != username:
        raise AppImageError("无权操作", 403)
    if body.name and body.name != row.name:
        raise AppImageError("AppImage 标识不可修改", 400)
    if not body.deploy_templates:
        raise AppImageError("deploy_templates 不能为空", 400)
    deploy_templates = normalize_kuscia_fields(body.deploy_templates)
    config_templates = body.config_templates or None
    if body.registry_source == "platform":
        repository = body.image_name.strip().strip("/")
        prefix = settings.platform_registry_project + "/"
        if repository.startswith(prefix): repository = repository[len(prefix):]
        image_name = f"{settings.platform_registry}/{settings.platform_registry_project}/{repository}"
        registry = settings.platform_registry
    else:
        image_name, registry = body.image_name.strip(), body.registry or (body.image_name.split("/", 1)[0] if "/" in body.image_name else "docker.io")
    try:
        get_kuscia_client().update_appimage(row.name, image_name, body.image_tag, deploy_templates, config_templates)
    except KusciaError as e:
        raise AppImageError(f"更新 Kuscia AppImage 失败: {e}", 502) from e
    for field in ("display_name", "description", "capability", "operations", "uc_capabilities", "registry_source", "registry", "image_tag", "job_template", "io_schema", "party_schema", "parameter_schema", "ui_schema", "task_input_template"):
        setattr(row, field, getattr(body, field))
    row.image_name, row.deploy_templates, row.config_templates = image_name, deploy_templates, config_templates
    db.commit(); db.refresh(row)
    return row
