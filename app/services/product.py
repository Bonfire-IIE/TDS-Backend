"""数据产品登记和目录管理。"""
from __future__ import annotations
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.identifier import gen_data_code
from app.models.catalog import DataCatalog
from app.models.contract_template import ContractTemplate
from app.models.product import DataProduct, DataProductResource
from app.schemas.product import ProductCreate, ProductPublish

class ProductError(Exception):
    def __init__(self, message: str, status_code: int = 400): self.message, self.status_code = message, status_code

def create(db: Session, username: str, is_operator: bool, body: ProductCreate) -> DataProduct:
    resources = _resources(db, body.resource_ids, username)
    baseline = [p.model_dump(by_alias=True) for p in body.baseline_policies]
    if not baseline and body.template_id:
        tpl = db.get(ContractTemplate, body.template_id)
        if not tpl: raise ProductError("合约模板不存在", 404)
        if tpl.scope == "user" and not is_operator and tpl.owner != username: raise ProductError("无权使用该合约模板", 403)
        baseline = tpl.policies or []
    provider_connector_id = resources[0].provider_connector_id
    row = DataProduct(
        tds_code=gen_data_code("product", settings.tds_default_subject_code, settings.tds_default_region_industry),
        name=body.name, description=body.description, product_type=body.product_type,
        industry_code=body.industry_code, region_code=body.region_code,
        time_range=body.time_range, application_scenarios=body.application_scenarios,
        personal_information_level=body.personal_information_level, delivery_method=body.delivery_method,
        public_data=body.public_data,
        usage_limitations=body.usage_limitations, authorization_required=body.authorization_required,
        data_subject_type=body.data_subject_type, data_size=body.data_size, update_frequency=body.update_frequency,
        applicable_model_types=body.applicable_model_types, ai_usage_scenarios=body.ai_usage_scenarios,
        provider_name=body.provider_name, provider_type=body.provider_type, provider_identity_id=body.provider_identity_id,
        provider_description=body.provider_description, provider_entity_info=body.provider_entity_info,
        operator_name=body.operator_name, operator_telephone=body.operator_telephone, operator_id_card=body.operator_id_card,
        declarations=body.declarations, platform_name=body.platform_name, platform_id=body.platform_id,
        platform_location=body.platform_location, delivery_mode=body.delivery_mode,
        measure_method=body.measure_method, measure_unit=body.measure_unit, price=body.price,
        delivery_info=body.delivery_info, resource_id=resources[0].id,
        provider_connector_id=provider_connector_id,
        transaction_mode=body.transaction_mode,
        baseline_policies=baseline, status="registered", created_by=username,
    )
    db.add(row); db.flush()
    for resource in resources: db.add(DataProductResource(product_id=row.id, resource_id=resource.id, processing_description=body.processing_description))
    db.commit(); db.refresh(row); return _enrich(db, row)

def _resources(db: Session, ids: list[str], owner: str) -> list[DataCatalog]:
    # Read source records under a row lock during registration/publication.
    rows = list(db.scalars(select(DataCatalog).where(DataCatalog.id.in_(ids)).with_for_update()).all())
    if not ids or len(ids) != len(set(ids)) or len(rows) != len(ids):
        raise ProductError("请选择存在且不重复的数据资源", 422)
    if any(r.created_by != owner for r in rows):
        raise ProductError("只能基于产品供数方自己的数据资源构建产品", 403)
    if any(r.status != "published" or r.deleted_at is not None for r in rows):
        raise ProductError("只能基于已公开到中心并通过审核的数据资源构建产品", 409)
    if len({r.provider_connector_id for r in rows}) != 1:
        raise ProductError("当前产品交付仅支持同一供数连接器的资源，请分别登记产品", 422)
    by_id = {r.id: r for r in rows}
    return [by_id[rid] for rid in ids]


def _enrich(db: Session, row: DataProduct) -> DataProduct:
    refs = list(db.scalars(select(DataProductResource).where(DataProductResource.product_id == row.id)).all())
    row.resource_ids = [ref.resource_id for ref in refs] or ([row.resource_id] if row.resource_id else [])
    sources = list(db.scalars(select(DataCatalog).where(DataCatalog.id.in_(row.resource_ids))).all()) if row.resource_ids else []
    row.resource_codes = [r.tds_code for r in sources if r.tds_code]
    descriptions = list(dict.fromkeys(ref.processing_description for ref in refs if ref.processing_description))
    row.processing_description = "；".join(descriptions) or None
    resource = next((r for r in sources if r.id == row.resource_id), None)
    row.resource_name = resource.name if resource else None
    return row

def list_products(db: Session, username: str, is_admin: bool) -> list[DataProduct]:
    stmt = select(DataProduct).where(DataProduct.deleted_at.is_(None)).order_by(DataProduct.created_at.desc())
    if not is_admin: stmt = stmt.where(or_(DataProduct.status == "listed", DataProduct.created_by == username))
    return [_enrich(db, r) for r in db.scalars(stmt).all()]

def get(db: Session, product_id: str) -> DataProduct:
    row = db.get(DataProduct, product_id)
    if not row or row.deleted_at is not None: raise ProductError("产品不存在", 404)
    return _enrich(db, row)

def update(db: Session, product_id: str, username: str, is_admin: bool, body: ProductCreate) -> DataProduct:
    row = get(db, product_id)
    if row.created_by != username and not is_admin: raise ProductError("无权修改该产品", 403)
    if row.status == "listed": raise ProductError("请先下架产品，再修改登记信息；已签合约保留原文档", 409)
    resources = _resources(db, body.resource_ids, row.created_by)
    for key, value in body.model_dump(exclude={"resource_ids", "baseline_policies", "template_id", "processing_description"}).items():
        if hasattr(row, key): setattr(row, key, value)
    row.baseline_policies = [p.model_dump(by_alias=True) for p in body.baseline_policies]
    db.query(DataProductResource).filter(DataProductResource.product_id == row.id).delete()
    for rid in body.resource_ids: db.add(DataProductResource(product_id=row.id, resource_id=rid, processing_description=body.processing_description))
    row.resource_id = body.resource_ids[0]
    row.provider_connector_id = resources[0].provider_connector_id
    db.commit(); db.refresh(row); return _enrich(db, row)

def delist(db: Session, product_id: str, username: str, is_operator: bool) -> DataProduct:
    row = get(db, product_id)
    if row.created_by != username and not is_operator: raise ProductError("无权操作", 403)
    row.status = "delisted"; db.commit(); db.refresh(row); return _enrich(db, row)

def delete_product(db: Session, product_id: str, username: str, is_admin: bool) -> None:
    row = get(db, product_id)
    if row.created_by != username and not is_admin: raise ProductError("无权删除该产品", 403)
    row.deleted_at = func.now(); db.commit()


def publish(db: Session, product_id: str, username: str, is_operator: bool, body: ProductPublish) -> DataProduct:
    row = get(db, product_id)
    if row.created_by != username and not is_operator: raise ProductError("无权上架该产品", 403)
    _resources(db, row.resource_ids, row.created_by)
    if not row.processing_description: raise ProductError("请先补充资源加工说明，再上架产品", 409)
    if row.status not in {"registered", "draft", "delisted", "listed"}: raise ProductError("当前产品状态不能上架", 409)
    for key, value in body.model_dump().items(): setattr(row, key, value)
    row.status = "listed"
    db.commit(); db.refresh(row)
    return _enrich(db, row)
