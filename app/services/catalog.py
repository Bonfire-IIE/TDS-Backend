"""数据目录业务逻辑：资源登记(建 DomainData) / 检索 / 下架 / 代码字典。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.code_tables import CODE_TABLES, TABLE_LABELS
from app.core.config import settings
from app.core.identifier import gen_data_code
from app.integrations.kuscia import KusciaError, get_kuscia_client, get_kuscia_lite_client
from app.models.catalog import CatalogCodeDict, DataCatalog
from app.models.connector import Connector
from app.models.datasource import DataSource
from app.models.product import DataProduct
from app.schemas.catalog import DataSourceCreate, ResourceCreate

# 平台承载的数据类型；仅 table 为结构化（带列定义）
DATA_TYPES = ("table", "image", "text", "file", "other")
# 平台仅承载 1-3 级数据（法律责任硬约束）
ALLOWED_SECURITY_LEVELS = ("1", "2", "3")


class CatalogError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---- 代码字典 ----
def seed_code_dict(db: Session) -> None:
    if db.execute(select(CatalogCodeDict).limit(1)).first():
        return
    for table_key, rows in CODE_TABLES.items():
        for code, name in rows:
            db.add(CatalogCodeDict(table_key=table_key, code=code, name_cn=name))
    db.commit()


def get_code_tables(db: Session) -> list[dict]:
    seed_code_dict(db)
    out = []
    for table_key, label in TABLE_LABELS.items():
        rows = db.execute(
            select(CatalogCodeDict).filter_by(table_key=table_key).order_by(CatalogCodeDict.code)
        ).scalars()
        out.append({
            "table_key": table_key,
            "label": label,
            "options": [{"code": r.code, "name": r.name_cn} for r in rows],
        })
    return out


# ---- 资源登记 ----
def register_resource(db: Session, username: str, is_operator: bool, body: ResourceCreate) -> DataCatalog:
    conn = db.get(Connector, body.provider_connector_id)
    if not conn:
        raise CatalogError("归属连接器不存在", 404)
    if conn.created_by != username:
        raise CatalogError("只能在自己的连接器下登记资源", 403)
    if conn.status != "approved":
        raise CatalogError("连接器未审批通过，无法登记资源", 409)

    # 安全等级上限=3（法律责任，硬约束）
    if body.security_level not in ALLOWED_SECURITY_LEVELS:
        raise CatalogError("平台不承载3级以上数据资源", 400)

    data_type = body.data_type or "table"
    if data_type not in DATA_TYPES:
        raise CatalogError(f"不支持的数据类型: {data_type}", 400)

    # 仅结构化(table)保留列定义并以 table 登记；非结构化以 unknown 登记且无列
    is_table = data_type == "table"
    columns = [c.model_dump() for c in body.columns] if is_table else []
    kuscia_type = "table" if is_table else "unknown"

    # 解析数据源：缺省 default-data-source 行为不变；否则引用平台 DataSource
    kuscia_ds_id, platform_ds_ref = _resolve_datasource(db, conn, body.datasource_id)

    tds_code = gen_data_code("resource", settings.tds_default_subject_code, settings.tds_default_region_industry)
    domaindata_id = "res-" + uuid.uuid4().hex[:12]
    relative_uri = body.relative_uri or f"{domaindata_id}.csv"
    attributes = {
        "tds_code": tds_code,
        "security_level": body.security_level,
        "resource_category": body.resource_category or "",
        "data_type": data_type,
    }
    try:
        get_kuscia_client().create_domaindata(
            domain_id=conn.kuscia_domain_id, domaindata_id=domaindata_id,
            name=body.name, relative_uri=relative_uri, columns=columns, attributes=attributes,
            datasource_id=kuscia_ds_id, kuscia_type=kuscia_type,
        )
    except KusciaError as e:
        raise CatalogError(f"创建 Kuscia DomainData 失败: {e}", 502) from e

    row = DataCatalog(
        tds_code=tds_code, name=body.name, description=body.description, kind="resource",
        data_type=data_type,
        provider_connector_id=conn.id, kuscia_domain_id=conn.kuscia_domain_id,
        kuscia_domaindata_id=domaindata_id,
        resource_category=body.resource_category, source_type=body.source_type,
        delivery_form=body.delivery_form, update_freq=body.update_freq,
        quality_level=body.quality_level, security_level=body.security_level,
        service_type=body.service_type, topic_category=body.topic_category,
        tags=body.tags, columns=columns, relative_uri=relative_uri,
        datasource_id=platform_ds_ref, status="registered", created_by=username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _enrich(db, row)


def _resolve_datasource(db: Session, conn: Connector, datasource_id: str) -> tuple[str, str]:
    """返回 (Kuscia 中的数据源ID, 平台侧存储的 datasource_id 引用)。"""
    if not datasource_id or datasource_id == "default-data-source":
        return "default-data-source", "default-data-source"
    ds = db.get(DataSource, datasource_id)
    if not ds:
        raise CatalogError("所选数据源不存在", 404)
    if ds.connector_id != conn.id:
        raise CatalogError("所选数据源不属于该连接器", 400)
    return ds.kuscia_datasource_id, ds.id


def _enrich(db: Session, row: DataCatalog) -> DataCatalog:
    """按 datasource_id 补充数据源展示信息（名称/类型/uri），供 CatalogOut 序列化。"""
    name = type_ = uri = None
    if row.datasource_id and row.datasource_id != "default-data-source":
        ds = db.get(DataSource, row.datasource_id)
        if ds:
            name, type_, uri = ds.name, ds.type, ds.uri
    else:
        name, type_, uri = "默认数据源(default-data-source)", "localfs", None
    row.datasource_name = name
    row.datasource_type = type_
    row.datasource_uri = uri
    return row


def search(db: Session, username: str, is_admin: bool, *, q: str | None = None,
           security_level: str | None = None, resource_category: str | None = None,
           connector_id: str | None = None) -> list[DataCatalog]:
    stmt = select(DataCatalog).where(DataCatalog.deleted_at.is_(None)).order_by(
        DataCatalog.created_at.desc()
    )
    # 可见性：普通用户仅能看到自己的数据资源；admin 看全部（均排除软删除）
    if not is_admin:
        stmt = stmt.where(DataCatalog.created_by == username)
    if q:
        stmt = stmt.where(DataCatalog.name.ilike(f"%{q}%"))
    if security_level:
        stmt = stmt.where(DataCatalog.security_level == security_level)
    if resource_category:
        stmt = stmt.where(DataCatalog.resource_category == resource_category)
    if connector_id:
        stmt = stmt.where(DataCatalog.provider_connector_id == connector_id)
    return [_enrich(db, r) for r in db.execute(stmt).scalars()]


def get(db: Session, catalog_id: str) -> DataCatalog:
    row = db.get(DataCatalog, catalog_id)
    if not row or row.deleted_at is not None:
        raise CatalogError("目录条目不存在", 404)
    return _enrich(db, row)


def delist(db: Session, catalog_id: str, username: str, is_operator: bool) -> DataCatalog:
    row = get(db, catalog_id)
    if row.created_by != username:
        raise CatalogError("无权操作", 403)
    row.status = "delisted"
    db.commit()
    db.refresh(row)
    return _enrich(db, row)


def delete_resource(db: Session, catalog_id: str, username: str, is_admin: bool) -> None:
    """软删除数据资源：同步删 Kuscia DomainData；仅打标记留档存证。

    - 属主或 admin 可删；
    - 存在未删除的数据产品引用则 409 拦截；
    - 删除 Kuscia DomainData 失败则 502。
    """
    row = get(db, catalog_id)  # 已排除软删
    if not (row.created_by == username or is_admin):
        raise CatalogError("无权删除该资源", 403)

    # 引用检查：仍有未删除的数据产品引用该资源 -> 拦截
    referenced = db.execute(
        select(DataProduct.id).where(
            DataProduct.resource_id == catalog_id,
            DataProduct.deleted_at.is_(None),
        ).limit(1)
    ).first()
    if referenced:
        raise CatalogError("该资源仍有数据产品引用，请先删除相关产品", 409)

    # 同步删 Kuscia DomainData
    if row.kuscia_domaindata_id:
        try:
            get_kuscia_client().delete_domaindata(
                domain_id=row.kuscia_domain_id, domaindata_id=row.kuscia_domaindata_id,
            )
        except KusciaError as e:
            raise CatalogError(f"删除 Kuscia DomainData 失败: {e}", 502) from e

    row.deleted_at = func.now()
    db.commit()


# ---- 数据源（DomainDataSource）----
def _check_connector_for_ds(db: Session, connector_id: str, username: str, is_operator: bool) -> Connector:
    conn = db.get(Connector, connector_id)
    if not conn:
        raise CatalogError("归属连接器不存在", 404)
    if conn.created_by != username:
        raise CatalogError("只能在自己的连接器下管理数据源", 403)
    if conn.status != "approved":
        raise CatalogError("连接器未审批通过，无法管理数据源", 409)
    return conn


def _build_datasource_info(body: DataSourceCreate) -> tuple[dict, str | None, dict]:
    """构造 (下发 Kuscia 的 info, 落库 uri, 落库非密 info)。AK/SK 绝不落库。"""
    if body.type == "localfs":
        path = body.info.get("path") or body.uri or "/home/kuscia/var/storage/data"
        kuscia_info = {"localfs": {"path": path}}
        return kuscia_info, path, {"path": path}
    if body.type == "oss":
        i = body.info or {}
        oss = {
            "endpoint": i.get("endpoint", ""),
            "bucket": i.get("bucket", ""),
            "prefix": i.get("prefix", ""),
            "access_key_id": i.get("access_key_id", ""),
            "access_key_secret": i.get("access_key_secret", ""),
            "storage_type": i.get("storage_type", ""),
            "virtualhost": bool(i.get("virtualhost", False)),
            "version": i.get("version", ""),
        }
        kuscia_info = {"oss": oss}
        uri = body.uri or f"{oss['endpoint'].rstrip('/')}/{oss['bucket']}/{oss['prefix']}".rstrip("/")
        # 落库仅保留非密字段（AK/SK 明文不落库；生产应加密或走 K8s Secret）
        stored = {k: oss[k] for k in ("endpoint", "bucket", "prefix", "storage_type", "virtualhost", "version")}
        return kuscia_info, uri, stored
    raise CatalogError("不支持的数据源类型（仅 localfs / oss）", 400)


def create_datasource(db: Session, username: str, is_operator: bool, body: DataSourceCreate) -> DataSource:
    if body.type not in ("localfs", "oss"):
        raise CatalogError("不支持的数据源类型（仅 localfs / oss）", 400)
    conn = _check_connector_for_ds(db, body.connector_id, username, is_operator)

    kuscia_ds_id = "ds-" + uuid.uuid4().hex[:12]
    kuscia_info, uri, stored_info = _build_datasource_info(body)
    # localfs 数据不出域 -> access_directly=True
    access_directly = True if body.type == "localfs" else body.access_directly
    try:
        if not conn.lite_api_endpoint or not conn.lite_api_port:
            raise CatalogError(f"连接器 {conn.name} 未配置 Lite KusciaAPI 端点和端口", 400)
        lite_endpoint = conn.lite_api_endpoint.rstrip(":/") + ":" + str(conn.lite_api_port)
        get_kuscia_lite_client(conn.kuscia_domain_id, lite_endpoint).create_domaindatasource(
            domain_id=conn.kuscia_domain_id, datasource_id=kuscia_ds_id,
            ds_type=body.type, name=body.name, info=kuscia_info, access_directly=access_directly,
        )
    except KusciaError as e:
        raise CatalogError(f"创建 Kuscia DomainDataSource 失败: {e}", 502) from e

    row = DataSource(
        name=body.name, type=body.type, connector_id=conn.id,
        kuscia_domain_id=conn.kuscia_domain_id, kuscia_datasource_id=kuscia_ds_id,
        uri=uri, info=stored_info, created_by=username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_datasources(db: Session, username: str, is_operator: bool,
                     connector_id: str | None = None) -> list:
    stmt = select(DataSource).order_by(DataSource.created_at.desc())
    if connector_id:
        stmt = stmt.where(DataSource.connector_id == connector_id)
    rows = list(db.execute(stmt).scalars())
    visible = [r for r in rows if r.created_by == username]
    if connector_id:
        conn = db.get(Connector, connector_id)
        if conn and conn.created_by == username:
            builtin = SimpleNamespace(
                id=f"builtin:{conn.id}:default-data-source",
                name="默认本地数据源", type="localfs", connector_id=conn.id,
                kuscia_domain_id=conn.kuscia_domain_id,
                kuscia_datasource_id="default-data-source",
                uri="/home/kuscia/var/storage/data",
                info={"path": "/home/kuscia/var/storage/data"},
                created_by="kuscia-system", created_at=conn.created_at,
                scope="builtin", deletable=False,
            )
            return [builtin, *visible]
    return visible


def get_datasource(db: Session, datasource_id: str, username: str, is_operator: bool) -> DataSource:
    row = db.get(DataSource, datasource_id)
    if not row:
        raise CatalogError("数据源不存在", 404)
    if row.created_by != username:
        raise CatalogError("无权查看该数据源", 403)
    return row


def report_datasource(db: Session, username: str, is_admin: bool, body) -> DataSource:
    """连接器门户上报：数据源已在本地 Lite 创建，中心仅落非密元数据（不碰 Lite）。

    按 (connector_id, kuscia_datasource_id) 幂等：已存在则更新，否则新建。
    """
    conn = db.get(Connector, body.connector_id)
    if not conn:
        raise CatalogError("归属连接器不存在", 404)
    if conn.created_by != username and not is_admin:
        raise CatalogError("只能上报自己连接器的数据源", 403)
    if body.type not in ("localfs", "oss"):
        raise CatalogError("不支持的数据源类型（仅 localfs / oss）", 400)
    existing = db.execute(
        select(DataSource).where(
            DataSource.connector_id == conn.id,
            DataSource.kuscia_datasource_id == body.kuscia_datasource_id,
        )
    ).scalars().first()
    if existing:
        existing.name, existing.type, existing.uri, existing.info = body.name, body.type, body.uri, body.info
        db.commit(); db.refresh(existing)
        return existing
    row = DataSource(
        name=body.name, type=body.type, connector_id=conn.id,
        kuscia_domain_id=conn.kuscia_domain_id, kuscia_datasource_id=body.kuscia_datasource_id,
        uri=body.uri, info=body.info, created_by=username,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def deregister_datasource(db: Session, datasource_id: str, username: str, is_admin: bool) -> None:
    """注销平台侧数据源记录（不碰 Lite；Lite 侧删除由门户完成）。被资源引用则拒。"""
    row = db.get(DataSource, datasource_id)
    if not row:
        raise CatalogError("数据源不存在", 404)
    if row.created_by != username and not is_admin:
        raise CatalogError("无权注销该数据源", 403)
    used = db.execute(
        select(DataCatalog.id).where(DataCatalog.datasource_id == row.id).limit(1)
    ).first()
    if used:
        raise CatalogError("该数据源已被数据资源引用，无法注销", 409)
    db.delete(row)
    db.commit()


def delete_datasource(db: Session, datasource_id: str, username: str, is_operator: bool) -> None:
    row = get_datasource(db, datasource_id, username, is_operator)
    # 被目录资源引用时禁止删除
    used = db.execute(
        select(DataCatalog.id).where(DataCatalog.datasource_id == row.id).limit(1)
    ).first()
    if used:
        raise CatalogError("该数据源已被数据资源引用，无法删除", 409)
    try:
        get_kuscia_lite_client(row.kuscia_domain_id).delete_domaindatasource(
            domain_id=row.kuscia_domain_id, datasource_id=row.kuscia_datasource_id,
        )
    except KusciaError as e:
        raise CatalogError(f"删除 Kuscia DomainDataSource 失败: {e}", 502) from e
    db.delete(row)
    db.commit()
