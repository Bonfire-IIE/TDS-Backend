from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services import catalog

class DB:
    def __init__(self, owner='alice', status='published', referenced=False):
        self.row=SimpleNamespace(id='r',created_by=owner,status=status,deleted_at=None,provider_connector_id='c')
        self.referenced=referenced
        self.statement=None
    def get(self, model, key):
        return SimpleNamespace(created_by='alice') if model.__name__=='Connector' else self.row
    def execute(self,stmt):self.statement=stmt;return self
    def first(self):return ('reference',) if self.referenced else None
    def scalars(self):return []
    def __iter__(self):return iter([])
    def commit(self):pass
    def refresh(self,row):pass

def test_resource_list_never_includes_other_owners_public_resources():
    db=DB();catalog.search(db,'alice',False)
    sql=str(db.statement.compile(compile_kwargs={'literal_binds':True}))
    assert "created_by = 'alice'" in sql
    assert "status = 'published'" not in sql

def test_delete_withdraws_projection_and_keeps_tombstone():
    db=DB();catalog.delete_resource(db,'r','alice',False)
    assert db.row.status=='delisted' and db.row.deleted_at is None
    catalog.delete_resource(db,'r','alice',False)
    assert db.row.status=='delisted'

def test_resource_withdrawal_does_not_implicitly_delist_products():
    with pytest.raises(catalog.CatalogError) as e:catalog.delist(DB(referenced=True),'r','alice',False)
    assert e.value.status_code==409

def test_other_owner_cannot_withdraw_but_governance_can():
    with pytest.raises(catalog.CatalogError) as e:catalog.delist(DB(),'r','bob',False)
    assert e.value.status_code==403
    assert catalog.delist(DB(),'r','operator',True).status=='delisted'
