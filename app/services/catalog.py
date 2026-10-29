"""数据目录业务逻辑：资源登记 / 检索 / 下架 / 代码字典。

下游执行系统资源只通过 DataResourceBinding 在 adapter 边界同步。
"""
from __future__ import annotations

import uuid
import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.code_tables import CODE_TABLES, TABLE_LABELS
from app.core.config import settings
from app.core.identifier import gen_data_code
from app.models.catalog import CatalogCodeDict, DataCatalog
from app.models.connector import Connector
from app.models.product import DataProduct, DataProductResource
from app.models.capability import DataResourceBinding
from app.schemas.catalog import ResourcePublish

# 平台承载的数据类型；仅 table 为结构化（带列定义）
DATA_TYPES = ("table", "image", "text", "file", "other")
# 平台仅承载 1-3 级数据（法律责任硬约束）
# The public schema uses the standard labels.  The service also accepts the
# numeric values emitted by pre-v2 connector clients and normalizes them at
# the boundary; they are never persisted or returned as numeric levels.
ALLOWED_SECURITY_LEVELS = ("general_1", "general_2", "important")
SECURITY_LEVEL_ALIASES = {"1": "general_1", "2": "general_2", "3": "important"}


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


def publish_resource(db: Session, username: str, body: ResourcePublish) -> DataCatalog:
    """接受连接器提交的资源目录投影，进入中心审核队列。"""
    if not re.fullmatch(r"V?[1-9][0-9]*", str(body.version_no or "")):
        raise CatalogError("资源公开必须携带连接器资源版本，请升级或修复资源同步客户端", 422)
    conn = db.get(Connector, body.source_connector_id)
    if not conn:
        raise CatalogError("归属连接器不存在", 404)
    if conn.created_by != username:
        raise CatalogError("只能提交自己连接器的资源", 403)
    if body.security_level == "core":
        raise CatalogError("核心数据不在本平台承载范围内", 400)
    if not re.fullmatch(r"[A-T]", body.industry_code.upper()):
        raise CatalogError("行业分类必须使用 GB/T 4754 的门类代码", 400)
    if body.theme_code and not re.fullmatch(r"Z[A-W](?:[A-Z]00)?", body.theme_code.upper()):
        raise CatalogError("政务主题分类必须使用 GB/T 21063.4 一级或二级代码", 400)
    columns = _validate_table_columns(body.data_items) if body.data_type == "table" else []
    if body.data_type != "table" and body.data_items:
        raise CatalogError("只有表格类数据资源可以配置列定义", 400)
    row = db.get(DataCatalog, body.resource_id)
    resource_code = (row.tds_code if row else None) or gen_data_code("resource", settings.tds_default_subject_code, settings.tds_default_region_industry)
    values = dict(
        id=body.resource_id, tds_code=resource_code, name=body.resource_name,
        description=body.resource_abstract, provider_connector_id=conn.id,
        data_type=body.data_type,
        industry_code=body.industry_code, theme_code=body.theme_code,
        resource_owner_name=body.resource_owner_name, resource_owner_id=body.resource_owner_id,
        contact_name=body.contact_name, contact_information=body.contact_information,
        resource_abstract=body.resource_abstract, resource_format=body.resource_format,
        source_type=body.data_source_type, update_freq=body.update_frequency,
        update_method=body.update_method, data_size=body.data_size, time_range=body.time_range,
        security_level=body.security_level, personal_information_level=body.personal_information_level,
        resource_quality=body.resource_quality, high_quality_flag=body.high_quality_flag,
        data_modalities=body.data_modalities, contains_synthetic_data=body.contains_synthetic_data,
        ai_readiness=body.ai_readiness, ai_task_types=body.ai_task_types,
        annotation_info=body.annotation_info, ai_training_authorization=body.ai_training_authorization,
        columns=columns, datasource_id=body.datasource_id,
        datasource_name=body.datasource_name, datasource_type=body.datasource_type,
        datasource_uri=body.datasource_uri,
        relative_uri=body.relative_uri, created_by=username, status="pending_review", deleted_at=None,
    )
    if row:
        if row.provider_connector_id != conn.id:
            raise CatalogError("资源已归属于其他连接器", 409)
        for key, value in values.items():
            if key != "id": setattr(row, key, value)
        row.status = "pending_review"
    else:
        row = DataCatalog(**values)
        db.add(row)
    db.flush()
    binding = db.scalar(select(DataResourceBinding).where(
        DataResourceBinding.platform_resource_id == row.id,
        DataResourceBinding.connector_id == conn.id,
    ))
    if not binding:
        binding = DataResourceBinding(platform_resource_id=row.id, connector_id=conn.id, source="connector")
        db.add(binding)
    binding.connector_resource_ref = body.resource_id
    binding.version = body.version_no
    binding.sync_status = "synced"
    binding.metadata_snapshot = {
        "name": body.resource_name, "data_type": body.data_type,
        "columns": columns,
        "datasource_ref": body.datasource_id,
        "connector_datasource_ref": body.datasource_id,
        "dr_resource_id": body.resource_id,
        "datasource_type": body.datasource_type,
        "relative_uri": body.relative_uri, "format": body.resource_format,
    }
    binding.last_synced_at = func.now()
    db.commit(); db.refresh(row)
    return _enrich(db, row)


def approve_resource(db: Session, catalog_id: str, comment: str | None = None) -> DataCatalog:
    row = db.get(DataCatalog, catalog_id)
    if not row or row.deleted_at is not None:
        raise CatalogError("资源不存在", 404)
    if row.status != "pending_review":
        raise CatalogError("只有待审核资源可以批准", 409)
    row.status = "published"
    row.review_comment = comment
    db.commit(); db.refresh(row)
    return _enrich(db, row)


def reject_resource(db: Session, catalog_id: str, comment: str) -> DataCatalog:
    row = db.get(DataCatalog, catalog_id)
    if not row or row.deleted_at is not None:
        raise CatalogError("资源不存在", 404)
    if row.status != "pending_review":
        raise CatalogError("只有待审核资源可以驳回", 409)
    row.status = "rejected"
    row.review_comment = comment
    db.commit(); db.refresh(row)
    return _enrich(db, row)


SEATUNNEL_SCALAR_TYPES = {
    "string", "boolean", "tinyint", "smallint", "int", "bigint",
    "float", "double", "bytes", "date", "time",
    "timestamp",
}
SEATUNNEL_DECIMAL = re.compile(r"^decimal\(([1-9]\d*),(\d+)\)$")


def _validate_table_columns(column_defs) -> list[dict]:
    """校验并归一化中心平台的表格列定义。

    当前连接器的结构化数据抽取由 SeaTunnel 2.3.8 执行，因此平台
    只接受当前表单能完整表达的 SeaTunnel 标量类型。复杂类型需要独立的
    嵌套 schema 设计，不在此处伪装成普通字符串放行。
    """
    if not column_defs:
        raise CatalogError("表格类数据资源必须提供列定义", 400)

    columns: list[dict] = []
    seen_names: set[str] = set()
    for column in column_defs:
        raw = column.model_dump() if hasattr(column, "model_dump") else vars(column)
        name = str(raw.get("name") or "").strip()
        column_type = str(raw.get("type") or "").strip().lower()
        if not name:
            raise CatalogError("表格列名不能为空", 400)
        if not column_type:
            raise CatalogError(f"表格列 {name} 的类型不能为空", 400)
        decimal = SEATUNNEL_DECIMAL.fullmatch(column_type)
        decimal_supported = bool(decimal and int(decimal.group(2)) <= int(decimal.group(1)) <= 38)
        if column_type not in SEATUNNEL_SCALAR_TYPES and not decimal_supported:
            supported = ", ".join(sorted(SEATUNNEL_SCALAR_TYPES)) + ", decimal(p,s)"
            raise CatalogError(
                f"表格列 {name} 的类型 {column_type} 不受支持，可选类型: {supported}",
                400,
            )
        if name in seen_names:
            raise CatalogError(f"表格列名重复: {name}", 400)
        seen_names.add(name)
        columns.append({
            "name": name,
            "type": column_type,
            "comment": str(raw.get("comment") or "").strip(),
        })
    return columns


def report_resource_binding(db: Session, username: str, body) -> DataResourceBinding:
    row = db.get(DataCatalog, body.platform_resource_id)
    if not row or row.deleted_at is not None:
        raise CatalogError("平台资源不存在", 404)
    conn = db.get(Connector, body.connector_id)
    if not conn or conn.created_by != username:
        raise CatalogError("只能上报自己拥有的连接器资源", 403)
    if row.provider_connector_id != conn.id:
        raise CatalogError("资源绑定必须由资源所属连接器上报", 403)
    if not re.fullmatch(r"V?[1-9][0-9]*", str(body.version or "")):
        raise CatalogError("资源绑定缺少有效发布版本，不能标记为已同步", 422)
    binding = db.scalar(select(DataResourceBinding).where(
        DataResourceBinding.platform_resource_id == row.id,
        DataResourceBinding.connector_id == conn.id,
    ))
    if not binding:
        binding = DataResourceBinding(platform_resource_id=row.id, connector_id=conn.id, source="connector")
        db.add(binding)
    binding.connector_resource_ref = body.connector_resource_ref
    binding.version = body.version
    binding.metadata_snapshot = body.metadata_snapshot or {}
    binding.sync_status = "synced"
    binding.last_synced_at = func.now()
    db.commit()
    db.refresh(binding)
    return binding


def _enrich(db: Session, row: DataCatalog, username: str | None = None, is_admin: bool = False) -> DataCatalog:
    connector = db.get(Connector, row.provider_connector_id)
    row.deletable = bool(is_admin or row.created_by == username or (connector and connector.created_by == username))
    return row


def search(db: Session, username: str, is_admin: bool, *, q: str | None = None,
           security_level: str | None = None, industry_code: str | None = None,
           connector_id: str | None = None) -> list[DataCatalog]:
    stmt = select(DataCatalog).where(DataCatalog.deleted_at.is_(None)).order_by(
        DataCatalog.created_at.desc()
    )
    # 资源投影仅供属主及治理人员访问；面向其他参与方公开的是产品。
    if not is_admin:
        stmt = stmt.where(DataCatalog.created_by == username)
    if q:
        stmt = stmt.where(DataCatalog.name.ilike(f"%{q}%"))
    if security_level:
        stmt = stmt.where(DataCatalog.security_level == security_level)
    if industry_code:
        stmt = stmt.where(DataCatalog.industry_code == industry_code)
    if connector_id:
        stmt = stmt.where(DataCatalog.provider_connector_id == connector_id)
    return [_enrich(db, r, username, is_admin) for r in db.execute(stmt).scalars()]


def get(db: Session, catalog_id: str) -> DataCatalog:
    row = db.get(DataCatalog, catalog_id)
    if not row or row.deleted_at is not None:
        raise CatalogError("目录条目不存在", 404)
    return _enrich(db, row)


def delist(db: Session, catalog_id: str, username: str, is_operator: bool) -> DataCatalog:
    """Withdraw a center projection, retaining its tombstone for edge reconciliation."""
    row = get(db, catalog_id)
    if row.created_by != username and not is_operator:
        raise CatalogError("无权撤回该资源投影", 403)
    if row.status == "delisted":
        return _enrich(db, row, username, is_operator)
    referenced = db.execute(
        select(DataProductResource.id).join(DataProduct, DataProduct.id == DataProductResource.product_id).where(
            DataProductResource.resource_id == catalog_id,
            DataProduct.deleted_at.is_(None),
        ).limit(1)
    ).first()
    if referenced:
        raise CatalogError("该资源仍被数据产品引用，请先解除产品引用后撤回资源投影", 409)
    row.status = "delisted"
    row.review_comment = "已撤回中心投影；连接器本地资源保留"
    db.commit()
    db.refresh(row)
    return _enrich(db, row, username, is_operator)


def delete_resource(db: Session, catalog_id: str, username: str, is_admin: bool) -> None:
    """Compatibility DELETE means withdrawal, never deletion of the edge resource.

    Keep the same visible-to-owner tombstone as /delist so reconciliation and
    retries can distinguish withdrawal from an outage or unknown identifier.
    """
    delist(db, catalog_id, username, is_admin)
