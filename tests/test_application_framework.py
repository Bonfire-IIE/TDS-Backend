"""Cross-layer regression tests for published templates and delegated execution."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.db import Base
from app.models import Connector, AppImage, DigitalContract, Project
from app.models.application_template import ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation, ExecutionIdentity
from app.services.application_template import check_definition, expand, digest, TemplateError

class ApplicationFrameworkTest(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(self.engine);self.db=Session(self.engine)
        for name in ['a','b','c','d','e']:
            self.db.add(Connector(id=name,name=name,org_name=name,created_by=name,status='active',csr_pem=name,csr_fingerprint=name,public_key_fingerprint=name))
        self.db.add(AppImage(id='image',name='test-component',display_name='component',capability='mpc',image_name='example/component',image_tag='v1',created_by='admin',status='registered',scope='custom',deploy_templates=[{'role':'sender'},{'role':'receiver'}],party_schema={'roles':[{'name':'sender','min':1,'max':1},{'name':'receiver','min':1,'max':1}]},io_schema={'inputs':[],'outputs':[{'name':'result','kind':'file','formats':['bin'],'role':'receiver'}]},parameter_schema={'type':'object','properties':{'size':{'type':'integer','minimum':1}},'required':['size']},task_input_template={'size':'{{parameters.size}}'}))
        doc={'contractInfo':{'expansionItem':{'computationOutsourcing':{'allowed':True}}},'contractPolicies':[{'executionNodeInfo':{'providerNodeId':'a','consumerNodeId':'b'},'subjectInfo':{'dataProductId':'p'}}]}
        self.db.add(DigitalContract(contract_id='contract',document=doc,document_hash='contract-hash',created_by='a'))
        self.p=Project(id='p',name='project',contract_id='contract',initiator_connector_id='b',created_by='b');self.db.add(self.p);self.db.commit()
        self.definition={'architecture':'cs','parameter_schema':{'type':'object','properties':{'batch':{'type':'integer','minimum':1,'default':64}}},'roles':[{'name':'owner','source':'provider'},{'name':'receiver','source':'consumer'}], 'tasks':[{'id':'first','app_image':'test-component','roles':{'sender':'owner','receiver':'receiver'},'parameters':{'size':{'parameter':'batch'}}},{'id':'second','app_image':'test-component','roles':{'sender':'owner','receiver':'receiver'},'parameters':{'size':{'parameter':'batch'}}}],'inputs':[],'outputs':[{'name':'result','task':'second','port':'result'}],'edges':[{'source':'first','target':'second','type':'control'}]}
    def tearDown(self):self.db.close();self.engine.dispose()
    def publish(self,d=None):
        if d and d.get('architecture')=='outsourced':
            app=self.db.get(AppImage,'image');app.party_schema={**app.party_schema,'architectures':['cs','outsourced']};self.db.flush()
        d=check_definition(self.db,d or self.definition);self.db.add(ApplicationTemplate(id='app',name='app',draft=d,created_by='admin'));v=ApplicationTemplateVersion(id='v',application_id='app',version=1,definition=d,definition_hash=digest(d));self.db.add(v);self.db.commit();return v
    def test_fanout_and_instance_isolation(self):
        self.publish();w=expand(self.db,self.p,{'applications':[{'id':'one','version_id':'v','parameters':{'batch':32}},{'id':'two','version_id':'v'}]})
        self.assertEqual([n['parameters']['size'] for n in w['nodes']],[32,32,64,64]);self.assertEqual(len({n['id'] for n in w['nodes']}),4)
    def test_type_validation_not_coerced(self):
        self.publish()
        with self.assertRaises(TemplateError):expand(self.db,self.p,{'applications':[{'id':'one','version_id':'v','parameters':{'batch':'32'}}]})
    def test_cycle_and_unknown_parameter(self):
        d=deepcopy(self.definition);d['edges'].append({'source':'second','target':'first','type':'control'})
        with self.assertRaisesRegex(TemplateError,'环'):check_definition(self.db,d)
        d=deepcopy(self.definition);d['tasks'][0]['parameters']['size']={'parameter':'unknown'}
        with self.assertRaisesRegex(TemplateError,'未知'):check_definition(self.db,d)
    def test_locked_roles(self):
        self.publish()
        with self.assertRaisesRegex(TemplateError,'锁定'):expand(self.db,self.p,{'applications':[{'id':'one','version_id':'v','roles':{'owner':'b'}}]})
    def test_snapshot_immutable(self):
        v=self.publish();app=self.db.get(AppImage,'image');app.image_tag='v2';self.db.commit();self.assertEqual(v.definition['appimage_snapshots']['test-component']['image_tag'],'v1')
    def test_outsourced_requires_active_scoped_delegation(self):
        d=deepcopy(self.definition);d['architecture']='outsourced';d['roles'][1]['source']='delegate:0';self.publish(d)
        w={'applications':[{'id':'one','version_id':'v'}]}
        with self.assertRaisesRegex(TemplateError,'委托'):expand(self.db,self.p,w)
        delegation=ComputationDelegation(id='del',project_id='p',version=1,status='active',scope={'instances':[{'id':'one','version_id':'v'}],'participants':[{'connector_id':'c','roles':['receiver']}]},scope_hash='hash',contract_hash='contract-hash',expires_at=datetime.now(timezone.utc)+timedelta(days=1),created_by='b');self.db.add(delegation);self.db.commit()
        self.assertEqual(expand(self.db,self.p,w)['nodes'][0]['parties'][1]['domain_id'],'c')
        delegation.status='revoked';self.db.commit()
        with self.assertRaises(TemplateError):expand(self.db,self.p,w)
    def test_standard_contract_extension_required(self):
        d=deepcopy(self.definition);d['architecture']='outsourced';self.publish(d);c=self.db.get(DigitalContract,'contract');c.document={**c.document,'contractInfo':{'expansionItem':{}}};self.db.commit()
        with self.assertRaisesRegex(TemplateError,'合约扩展'):expand(self.db,self.p,{'applications':[{'id':'one','version_id':'v'}]})
    def test_optional_parameter_mapping_is_omitted(self):
        app=self.db.get(AppImage,'image');app.parameter_schema={**app.parameter_schema,'required':[]}
        d=deepcopy(self.definition);d['parameter_schema']['properties']['batch'].pop('default')
        self.publish(d)
        self.assertEqual(expand(self.db,self.p,{'applications':[{'id':'one','version_id':'v'}]})['nodes'][0]['parameters'],{})
    def test_structural_errors_are_user_errors(self):
        for change in [{'tasks':[None]},{'roles':[None]},{'parameter_schema':{'properties':[]}}]:
            with self.subTest(change=change),self.assertRaises(TemplateError):check_definition(self.db,{**self.definition,**change})
        self.publish()
        with self.assertRaises(TemplateError):expand(self.db,self.p,{'applications':[None]})
    def test_cs_component_cannot_be_scheduled_as_outsourced(self):
        d=deepcopy(self.definition);d['architecture']='outsourced'
        with self.assertRaisesRegex(TemplateError,'未声明支持 outsourced'):check_definition(self.db,d)
    def test_distinct_roles_need_verified_institutions(self):
        d=deepcopy(self.definition);d['distinct_roles']=[['owner','receiver']];self.publish(d)
        w={'applications':[{'id':'one','version_id':'v'}]}
        with self.assertRaisesRegex(TemplateError,'核验'):expand(self.db,self.p,w)
        for cid in ['a','b']:self.db.add(ExecutionIdentity(connector_id=cid,subject_id='same-org',verified_by='admin'))
        self.db.commit()
        with self.assertRaisesRegex(TemplateError,'不同主体'):expand(self.db,self.p,w)
        self.db.get(ExecutionIdentity,'b').subject_id='other-org';self.db.commit()
        self.assertEqual(len(expand(self.db,self.p,w)['nodes']),2)


    def test_detached_application_keeps_immutable_provenance_but_allows_parameters_edges(self):
        self.publish();origin={'id':'one','version_id':'v'}
        w=expand(self.db,self.p,{'applications':[origin]})
        detached={'detached_applications':[origin],'nodes':deepcopy(w['nodes']),'edges':[]}
        for n in detached['nodes']:n['detached']=True;n['parameters']['size']=5
        result=expand(self.db,self.p,detached)
        self.assertEqual(result['nodes'][0]['parameters']['size'],5)
        for key,value in [('app_image','other'),('template_version','wrong'),('id','copied')]:
            forged=deepcopy(detached);forged['nodes'][0][key]=value
            with self.assertRaises(TemplateError):expand(self.db,self.p,forged)
        forged=deepcopy(detached);forged['nodes'][0]['parties'][0]['domain_id']='c'
        with self.assertRaises(TemplateError):expand(self.db,self.p,forged)
        forged=deepcopy(detached);forged['nodes'].pop()
        with self.assertRaises(TemplateError):expand(self.db,self.p,forged)
