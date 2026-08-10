"""数据产品业务逻辑：上架 / 目录浏览 / 下架。"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_data_code
from app.models.catalog import DataCatalog
from app.models.contract_template import ContractTemplate
from app.models.product import DataProduct
from app.schemas.product import ProductCreate


class ProductError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create(db: Session, username: str, is_operator: bool, body: ProductCreate) -> DataProduct:
    resource = db.get(DataCatalog, body.resource_id)
    if not resource:
        raise ProductError("底层资源不存在", 404)
    if resource.deleted_at is not None:
        raise ProductError("底层资源已删除", 409)
    if resource.created_by != username:
        raise ProductError("只能基于自己的资源上架产品", 403)
    if resource.status != "registered":
        raise ProductError("资源未处于已登记状态，无法上架", 409)

    # 基准策略来源：显式 baseline_policies 优先；否则若指定 template_id 则取模板 policies
    baseline = [p.model_dump(by_alias=True) for p in body.baseline_policies]
    if not baseline and body.template_id:
        tpl = db.get(ContractTemplate, body.template_id)
        if not tpl:
            raise ProductError("合约模板不存在", 404)
        # 可见性：system 模板对所有人可用；user 模板仅属主/运营方可用
        if tpl.scope == "user" and not is_operator and tpl.owner != username:
            raise ProductError("无权使用该合约模板", 403)
        baseline = tpl.policies or []

    tds_code = gen_data_code(
        "product", settings.tds_default_subject_code, settings.tds_default_region_industry
    )
    row = DataProduct(
        tds_code=tds_code,
        name=body.name,
        description=body.description,
        resource_id=resource.id,
        provider_connector_id=resource.provider_connector_id,
        kuscia_domain_id=resource.kuscia_domain_id,
        transaction_mode=body.transaction_mode,
        baseline_policies=baseline,
        allowed_appimages=body.allowed_appimages or [],
        status="listed",
        created_by=username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _attach_resource_name(db: Session, row: DataProduct) -> DataProduct:
    """附加关联资源名称（非持久化的临时属性，供响应展示）。"""
    resource = db.get(DataCatalog, row.resource_id)
    row.resource_name = resource.name if resource else None
    return row


def list_products(db: Session, username: str, is_admin: bool) -> list[DataProduct]:
    stmt = select(DataProduct).where(DataProduct.deleted_at.is_(None)).order_by(
        DataProduct.created_at.desc()
    )
    # 可见性：已上架对所有登录用户可见；下架的仅属主/admin 可见（均排除软删除）
    if not is_admin:
        stmt = stmt.where(
            or_(DataProduct.status == "listed", DataProduct.created_by == username)
        )
    rows = list(db.execute(stmt).scalars())
    return [_attach_resource_name(db, r) for r in rows]


def get(db: Session, product_id: str) -> DataProduct:
    row = db.get(DataProduct, product_id)
    if not row or row.deleted_at is not None:
        raise ProductError("产品不存在", 404)
    return _attach_resource_name(db, row)


def delist(db: Session, product_id: str, username: str, is_operator: bool) -> DataProduct:
    row = get(db, product_id)
    if row.created_by != username:
        raise ProductError("无权操作", 403)
    row.status = "delisted"
    db.commit()
    db.refresh(row)
    return row


def delete_product(db: Session, product_id: str, username: str, is_admin: bool) -> None:
    """软删除数据产品：无 Kuscia 对象，纯软删（仅打标记留档存证）。"""
    row = get(db, product_id)  # 已排除软删
    if not (row.created_by == username or is_admin):
        raise ProductError("无权删除该产品", 403)
    row.deleted_at = func.now()
    db.commit()
