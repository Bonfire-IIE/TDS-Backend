from app.services.execution_compat import normalize_execution_request

def test_legacy_privacy_request_gets_generic_aliases_without_engine_ids():
    value = normalize_execution_request({
        'application': {'code': 'bpsi-csv-keys-v1'},
        'provider_connector_id': 'provider', 'consumer_connector_id': 'consumer',
        'provider_execution_node_ref': 'p-domain', 'consumer_execution_node_ref': 'c-domain',
        'input_provider_ref': 'provider-resource', 'input_consumer_ref': 'consumer-resource',
    }, scheduling_mode='master-lite')
    assert value['scheduling_mode'] == 'master-lite'
    assert value['applications']['bpsi-csv-keys-v1']['code'] == 'bpsi-csv-keys-v1'
    assert {p['connector_id'] for p in value['participants']} == {'provider', 'consumer'}
    assert value['provider_resource_ref'] == 'provider-resource'
    assert value['consumer_resource_ref'] == 'consumer-resource'
    assert 'job_id' not in value and 'domain_data_id' not in value

def test_generic_request_is_not_overwritten():
    request={'scheduling_mode':'autonomy','applications':{'app':{}},'participants':[{'connector_id':'x'}], 'provider_resource_ref':'new'}
    assert normalize_execution_request(request, scheduling_mode='master-lite') == request

def test_legacy_application_mapping_uses_actual_workflow_image_name():
    value=normalize_execution_request({'application':{'code':'business-code'},'workflow':{'nodes':[{'app_image':'registered-image'}]}})
    assert set(value['applications'])=={'registered-image'}

def test_legacy_materialization_uses_project_runtime_and_result_lifecycle():
    from types import SimpleNamespace
    from app.services.execution_compat import materialize_execution_request
    app=SimpleNamespace(io_schema={'outputs':[{'name':'result','formats':['bin']}]})
    value=materialize_execution_request({'workflow':{'nodes':[{'id':'single','app_image':'image','output_bindings':[{'port':'result','domain_id':'owner'}]}],'edges':[]}}, {'image':app},project_id='project',run_id='run')
    assert value['workflow']['nodes'][0]['output_bindings'][0]['relative_uri']=='projects/project/run/single-result.bin'
    assert value['artifact_plan']==[{'connector_id':'owner','node':'single','port':'result','relative_uri':'projects/project/run/single-result.bin','retention':'result'}]

def test_legacy_materialization_resolves_existing_consumer_output_convention():
    from types import SimpleNamespace
    from app.services.execution_compat import materialize_execution_request
    app=SimpleNamespace(io_schema={'outputs':[{'name':'result','formats':['csv']}]})
    request={'consumer_connector_id':'consumer','workflow':{'nodes':[{'id':'single','app_image':'image','parties':[{'connector_id':'consumer','role':'receiver'}],'input_bindings':[{'port':'source','connector_id':'consumer','domaindata_id':'resource'}],'output_bindings':[{'port':'result'}]}],'edges':[]}}
    value=materialize_execution_request(request,{'image':app},project_id='project',run_id='run')
    node=value['workflow']['nodes'][0]
    assert node['input_bindings'][0]['domain_id']=='consumer'
    assert node['output_bindings'][0]['domain_id']=='consumer'
    assert value['artifact_plan'][0]['connector_id']=='consumer'
    assert 'domain_id' not in request['workflow']['nodes'][0]['parties'][0]
