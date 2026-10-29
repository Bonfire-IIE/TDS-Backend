import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Connector, DataCatalog, DigitalContract, Project, AppImage
from app.models.product import DataProduct, DataProductResource
from app.models.capability import DataResourceBinding
from app.services import project as service

@pytest.fixture
def scenario(monkeypatch):
    monkeypatch.setattr(service.settings, 'pets_scheduler_mode', 'master-lite')
    engine=create_engine('sqlite://')
    for model in [Connector,DataCatalog,DataProduct,DataProductResource,DataResourceBinding,DigitalContract,Project,AppImage]: model.__table__.create(engine)
    with Session(engine) as db:
        for cid in ['provider','consumer','third']:
            db.add(Connector(id=cid,name=cid,tds_code='code-'+cid,created_by=cid,csr_pem='',csr_fingerprint=cid,public_key_fingerprint=cid))
        for rid,owner,status,kind,fmt in [('contract','provider','published','oss','CSV'),('unbound','provider','published','localfs','CSV'),('own','consumer','published','oss','CSV'),('own2','consumer','published','jdbc','TABLE'),('private','consumer','registered','localfs','CSV'),('other','third','published','localfs','CSV')]:
            db.add(DataCatalog(id=rid,name=rid,provider_connector_id=owner,datasource_id='source',datasource_type=kind,resource_format=fmt,relative_uri=rid+'.csv',data_type='table',created_by=owner,status=status))
            db.add(DataResourceBinding(platform_resource_id=rid,connector_id=owner,connector_resource_ref=rid,sync_status='synced',metadata_snapshot={'datasource_type':kind}))
        db.add(DataProduct(id='product',name='product',created_by='provider',resource_id='contract'))
        db.add(DataProductResource(product_id='product',resource_id='contract'))
        db.add(DigitalContract(contract_id='contract-id',created_by='consumer',document_hash='hash',document={'contractPolicies':[{'subjectInfo':{'dataProductId':'product'},'executionNodeInfo':{'providerNodeId':'code-provider','consumerNodeId':'code-consumer'}}]}))
        p=Project(id='project',name='project',contract_id='contract-id',initiator_connector_id='consumer',created_by='consumer');db.add(p)
        db.add(AppImage(name='psi',display_name='PSI',capability='PSI',created_by='admin',registry='example',image_name='psi',image_tag='v1',status='registered',deploy_templates=[{'role':'provider'},{'role':'consumer'}],party_schema={'roles':[{'name':'provider','required':True,'max':1},{'name':'consumer','required':True,'max':1}]},io_schema={'inputs':[{'name':'sender','kind':'table','formats':['csv'],'source_types':['localfs'],'role':'provider'},{'name':'receiver','kind':'table','formats':['csv'],'source_types':['localfs'],'role':'consumer'}],'outputs':[]},parameter_schema={}))
        db.commit();yield db,p

def workflow(provider='contract',consumer='own',consumer_domain='consumer'):
    return {'nodes':[{'id':'psi','app_image':'psi','parties':[{'domain_id':'provider','role':'provider'},{'domain_id':'consumer','role':'consumer'}],'input_bindings':[{'port':'sender','domain_id':'provider','domaindata_id':provider},{'port':'receiver','domain_id':consumer_domain,'domaindata_id':consumer}]}],'edges':[]}

def test_candidates_follow_contract_and_consumer_scope(scenario):
    db,p=scenario
    rows=service.available_domain_data(db,p,'consumer')
    assert {r['resource_id'] for r in rows}=={'contract','own','own2'}
    provider=next(r for r in rows if r['resource_id']=='contract')
    assert provider['selection_scope']=='contract'
    assert provider['datasource_type']=='oss'
    assert (provider['input_source_type'],provider['input_format'])==('localfs','csv')
    assert {r['resource_id'] for r in service.available_domain_data(db,p,'provider')}=={'contract','own','own2'}

def test_master_prepared_oss_and_jdbc_inputs_are_accepted(scenario):
    db,p=scenario
    service.validate_workflow(db,p,workflow())
    service.validate_workflow(db,p,workflow(consumer='own2'))

@pytest.mark.parametrize('values,code', [({'provider':'unbound'},403),({'consumer':'other','consumer_domain':'third'},403),({'consumer':'private'},400)])
def test_manual_dsl_cannot_bypass_scope(scenario,values,code):
    db,p=scenario
    with pytest.raises(service.ProjectError) as error: service.validate_workflow(db,p,workflow(**values))
    assert error.value.status_code==code

def test_removed_or_unsynced_resource_not_selectable(scenario):
    db,p=scenario
    db.get(DataCatalog,'contract').deleted_at=__import__('datetime').datetime.now()
    db.query(DataResourceBinding).filter_by(platform_resource_id='own').one().sync_status='failed';db.commit()
    assert {r['resource_id'] for r in service.available_domain_data(db,p,'consumer')}=={'own2'}

def test_forged_intermediate_binding_cannot_skip_resource_authorization(scenario):
    db,p=scenario;value=workflow(provider='unbound')
    value['nodes'][0]['input_bindings'][0]['source_node']='pretend-authorized'
    with pytest.raises(service.ProjectError,match='自动生成'):service.validate_workflow(db,p,value)

def test_data_edge_cannot_override_existing_external_input(scenario):
    from copy import deepcopy
    db,p=scenario;value=workflow();other=deepcopy(value['nodes'][0]);other['id']='second';value['nodes'].append(other)
    value['edges']=[{'source':'psi','source_handle':'output','target':'second','target_handle':'sender','type':'data'}]
    with pytest.raises(service.ProjectError,match='一个数据来源'):service.validate_workflow(db,p,value)


@pytest.mark.parametrize("data_type", ["file", "image", "text"])
def test_file_port_accepts_binary_file_classifications(scenario, data_type):
    from copy import deepcopy
    db,p=scenario
    resource=db.get(DataCatalog,"own")
    resource.data_type=data_type
    resource.resource_format="BINARY"
    resource.relative_uri="query.png"
    app=db.query(AppImage).filter_by(name="psi").one()
    schema=deepcopy(app.io_schema)
    schema["inputs"][1].update(kind="file",formats=["binary"],source_types=["oss"])
    app.io_schema=schema
    db.commit()
    service.validate_workflow(db,p,workflow())


@pytest.mark.parametrize("restriction,error", [
    ({"data_types":["file"]}, "不接受 image 数据"),
    ({"formats":["csv"]}, "不接受 binary 格式"),
    ({"source_types":["localfs"]}, "不接受 oss 数据源"),
    ({"kind":"table"}, "不接受 image 数据"),
])
def test_file_compatibility_preserves_explicit_restrictions(scenario, restriction, error):
    from copy import deepcopy
    db,p=scenario
    resource=db.get(DataCatalog,"own")
    resource.data_type="image"
    resource.resource_format="BINARY"
    app=db.query(AppImage).filter_by(name="psi").one()
    schema=deepcopy(app.io_schema)
    schema["inputs"][1].update(kind="file",formats=["binary"],source_types=["oss"])
    schema["inputs"][1].update(restriction)
    app.io_schema=schema
    db.commit()
    with pytest.raises(service.ProjectError,match=error):
        service.validate_workflow(db,p,workflow())
