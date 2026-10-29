from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.schemas.contract import ContractRequest, ProposeRequest
from app.services import contract as svc

@pytest.mark.parametrize('value', [
    {'signatureList':[]}, {'computationOutsourcing':{'allowed':'true'}},
    {'computationOutsourcing':{'allowed':True,'allowedConnectors':['a','a']}},
    {'computationOutsourcing':{'allowed':True,'roles':['compute']}},
])
def test_outsourcing_cannot_replace_standard_or_unknown_fields(value):
    with pytest.raises(svc.ContractError):svc._outsourcing_extension(value)

def test_request_extension_only_permits_negotiated_contract(monkeypatch):
    monkeypatch.setattr(svc,'validate_document',lambda d:d)
    product=SimpleNamespace(name='model',description='model',id='product',transaction_mode='negotiate',baseline_policies=[])
    provider=SimpleNamespace(tds_code='provider',id='a',org_name='A',name='A')
    consumer=SimpleNamespace(tds_code='consumer',id='b',org_name='B',name='B')
    ext={'computationOutsourcing':{'allowed':True,'allowedConnectors':['c','d','e']}}
    body=ContractRequest(consumer_connector_id='b',contract_expansion=ext)
    doc=svc._document(product,provider,consumer,'contract','user',body)
    assert doc['contractInfo']['expansionItem']['computationOutsourcing']==ext['computationOutsourcing']
    assert doc['contractInfo']['expansionItem']['businessType']=='DATA_PRODUCT_USAGE'
    assert doc['contractPolicies'][0]['policyExpansion']['resultType']['type']=='application_output'
    assert [e['signatoryEntityId'] for e in doc['contractInfo']['signatoryEntities']]==['provider','consumer']
    assert doc['contractPolicies'][0]['executionNodeInfo']['consumerNodeId']=='consumer'
    product.transaction_mode='accept'
    with pytest.raises(svc.ContractError,match='自行扩权'):svc._document(product,provider,consumer,'contract','user',body)

def test_extension_proposal_preserves_parties_and_requires_new_signatures(monkeypatch):
    original={'contractInfo':{'contractStatus':'filed','signatoryEntities':[{'id':'a'},{'id':'b'}], 'signatureList':[{'signature':'old'}],'signTime':'old','expansionItem':{'purpose':'inference'}},'contractPolicies':[{'id':'policy'}]}
    row=SimpleNamespace(document=deepcopy(original),current_version=1)
    monkeypatch.setattr(svc,'get',lambda *args:row)
    saved=[];monkeypatch.setattr(svc,'_save_version',lambda db,c,doc,op,user:saved.append(doc))
    db=SimpleNamespace(commit=lambda:None,refresh=lambda r:None)
    svc.propose(db,'contract','user',False,ProposeRequest(contract_policies=[{'id':'new'}],contract_expansion={'computationOutsourcing':{'allowed':True}}))
    result=saved[0]
    assert result['contractInfo']['signatoryEntities']==original['contractInfo']['signatoryEntities']
    assert result['contractInfo']['signatureList']==[] and result['contractInfo']['signTime'] is None
    assert result['contractInfo']['expansionItem']['purpose']=='inference'
    assert result['contractInfo']['expansionItem']['computationOutsourcing']=={'allowed':True}
    assert row.document==original  # signing material wasn't mutated in-place
