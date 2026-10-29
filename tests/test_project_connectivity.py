from datetime import datetime,timezone
from types import SimpleNamespace
from app.services import project as svc,execution_dispatch

def rig(monkeypatch):
    monkeypatch.setattr(svc.settings,'pets_scheduler_mode','autonomy')
    conns=[SimpleNamespace(id=x,status='active') for x in ['a','b']]
    caps={x:SimpleNamespace(evidence={'network':{'connector_endpoint':'http://'+x,'gateway_endpoint':'http://'+x+':1080'}}) for x in ['a','b']}
    targets={x:(caps[x],caps[x].evidence['network']) for x in caps}
    monkeypatch.setattr(svc,'_connectivity_context',lambda *_:(conns,targets,'scope'))
    return SimpleNamespace(commit=lambda:None),SimpleNamespace(id='p'),caps

def test_active_connectors_without_probe_are_unknown(monkeypatch):
    db,p,_=rig(monkeypatch);value=svc.connectivity_status(db,p)
    assert not value['connected'] and {x['state'] for x in value['pairs']}=={'unknown'}

def test_ensure_persists_each_direction_and_scope_invalidation(monkeypatch):
    db,p,caps=rig(monkeypatch);calls=[]
    def post(endpoint,pid,cid,action,body,timeout):
        calls.append((cid,action))
        if action=='identity':return {'connector_id':cid,'domain_id':'domain-'+cid,'cert':'cert'}
        return {'src':cid,'dst':body['peer_identity']['connector_id'],'state':'ready','ready':True,'checked_at':datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(execution_dispatch,'_post',post)
    assert svc.ensure_connectivity(db,p)['connected']
    assert calls==[('a','identity'),('b','identity'),('a','connectivity'),('b','connectivity')]
    caps['a'].evidence['connectivity']['p']['scope_hash']='changed'
    assert not svc.connectivity_status(db,p)['connected']

def test_context_selects_capability_by_stable_primary_key(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.db import Base
    from app.models import Connector,ConnectorCapability
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        conn=Connector(id='a',name='A',created_by='a',status='active',csr_pem='a',csr_fingerprint='a',public_key_fingerprint='a');db.add(conn)
        db.add_all([ConnectorCapability(id='z-last',connector_id='a',capability_code='first-inserted',status='verified',evidence={'network':{'connector_endpoint':'http://z'}}),ConnectorCapability(id='a-first',connector_id='a',capability_code='last-inserted',status='verified',evidence={'network':{'connector_endpoint':'http://a'}})])
        db.commit();monkeypatch.setattr(svc,'execution_domains',lambda *_:[conn])
        _,targets,scope=svc._connectivity_context(db,SimpleNamespace(id='p'))
        assert targets['a'][0].id=='a-first'
        targets['a'][0].evidence={**targets['a'][0].evidence,'connectivity':{'p':{'pairs':{}}}};db.commit()
        _,again,scope_again=svc._connectivity_context(db,SimpleNamespace(id='p'))
        assert again['a'][0].id=='a-first' and scope_again==scope
    engine.dispose()
