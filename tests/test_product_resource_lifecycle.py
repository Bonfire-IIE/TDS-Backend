"""Products derive from owned, published resources; registration is private until listing."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app.models.catalog import DataCatalog
from app.models.product import DataProduct, DataProductResource
from app.models.contract_template import ContractTemplate
from app.schemas.product import ProductCreate, ProductPublish
from app.services import product

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    for model in (DataCatalog,DataProduct,DataProductResource,ContractTemplate):model.__table__.create(engine)
    with Session(engine) as session:
        for rid,owner,connector,status in [('r1','alice','c1','published'),('r2','alice','c1','published'),('r3','bob','c2','published'),('r4','alice','c1','pending_review'),('r5','alice','c3','published')]:
            session.add(DataCatalog(id=rid,name=rid,tds_code='resource-'+rid,provider_connector_id=connector,industry_code='J',datasource_id='source',created_by=owner,status=status))
        session.commit();yield session


def body(**changes):
    values=dict(name='统计产品',description='汇总统计数据集',product_type='01',industry_code='J',application_scenarios='经营分析',personal_information_level='0',delivery_method='01',usage_limitations='不得转售',data_subject_type='02',update_frequency='1次/月',provider_name='供方',provider_type='02',provider_identity_id='subject-alice',provider_description='提供方简介',declarations={'compliance':'a','data_source':'b','ai_training_license':'c'},resource_ids=['r1','r2'],processing_description='清洗两个数据源、按月聚合后形成统计指标',baseline_policies=[{'type':'allow','actions':['read']}])
    values.update(changes);return ProductCreate(**values)


def listing():
    return ProductPublish(platform_name='测试中心',platform_id='node-test',platform_location='北京',delivery_mode='01',measure_method='按次',measure_unit='元/次',price=0,delivery_info='通过连接器交付 CSV')


def test_registration_lineage_listing_and_withdrawal(db):
    row=product.create(db,'alice',False,body())
    assert row.status=='registered' and row.tds_code
    assert set(row.resource_codes)=={'resource-r1','resource-r2'}
    assert row.processing_description==body().processing_description
    assert row.provider_connector_id=='c1' and row.provider_identity_id=='subject-alice'
    assert not product.list_products(db,'bob',False)
    product.publish(db,row.id,'alice',False,listing())
    assert product.list_products(db,'bob',False)[0].id==row.id
    with pytest.raises(product.ProductError):product.update(db,row.id,'alice',False,body(name='不可静默替换'))
    product.delist(db,row.id,'alice',False)
    assert not product.list_products(db,'bob',False)
    assert db.get(DataCatalog,'r1').status=='published'
    updated=product.update(db,row.id,'alice',False,body(resource_ids=['r2'],processing_description='仅对第二份资源脱敏处理'))
    assert updated.resource_ids==['r2']
    assert len(list(db.scalars(select(DataProductResource).where(DataProductResource.product_id==row.id))))==1
    product.publish(db,row.id,'alice',False,listing())
    assert row.status=='listed'

@pytest.mark.parametrize('ids,code',[(['r3'],403),(['r4'],409),(['r1','r5'],422),(['missing'],422)])
def test_unavailable_or_foreign_sources_rejected_even_for_governance(db,ids,code):
    with pytest.raises(product.ProductError) as error:product.create(db,'alice',True,body(resource_ids=ids))
    assert error.value.status_code==code
    assert not list(db.scalars(select(DataProduct)))


def test_revalidate_sources_on_publish_and_owner_on_admin_update(db):
    row=product.create(db,'alice',False,body())
    db.get(DataCatalog,'r1').status='delisted';db.commit()
    with pytest.raises(product.ProductError) as error:product.publish(db,row.id,'alice',False,listing())
    assert error.value.status_code==409 and row.status=='registered'
    with pytest.raises(product.ProductError):product.update(db,row.id,'admin',True,body(resource_ids=['r3']))
    assert set(product.get(db,row.id).resource_ids)=={'r1','r2'}


def test_validation_requires_processing_unique_sources_and_real_listing_fields():
    for changes in ({'processing_description':' '},{'resource_ids':['r1','r1']},{'resource_ids':[]}):
        with pytest.raises(ValidationError):body(**changes)
    with pytest.raises(ValidationError):ProductPublish(**{**listing().model_dump(),'price':-1})
    with pytest.raises(ValidationError):ProductPublish(**{**listing().model_dump(),'delivery_info':' '})
