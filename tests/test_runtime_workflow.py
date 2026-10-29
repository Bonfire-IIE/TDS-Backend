from types import SimpleNamespace

from app.services.project import _resolve_application_contract, _runtime_application, _runtime_workflow


def app(name, inputs, outputs):
    return SimpleNamespace(
        name=name, display_name=name.title(), description="test application",
        capability="mpc", operations=["process"], uc_capabilities=["ephemeral"],
        registry_source="third_party", registry="example", scope="custom", status="registered",
        image_name=f"example/{name}", image_tag="v1",
        deploy_templates=[], config_templates={}, job_template={},
        io_schema={"inputs": inputs, "outputs": outputs}, party_schema={},
        parameter_schema={"type": "object"}, ui_schema={},
        task_input_template={"input": "{{inputs.source.relative_uri}}"},
    )


def test_runtime_workflow_materializes_data_edges_without_csv_assumption():
    first = app("producer", [], [{"name": "records", "formats": ["parquet"]}])
    second = app("consumer", [{"name": "source", "formats": ["parquet"]}], [])
    workflow = {
        "nodes": [
            {"id": "produce", "app_image": "producer", "parties": [{"domain_id": "a", "role": "writer"}]},
            {"id": "consume", "app_image": "consumer", "parties": [{"domain_id": "a", "role": "reader"}]},
        ],
        "edges": [{"type": "data", "source": "produce", "source_handle": "records",
                   "target": "consume", "target_handle": "source"}],
    }

    result = _runtime_workflow(
        workflow,
        {"producer": first, "consumer": second},
        "project-1", "12345678-run",
    )

    output = result["nodes"][0]["output_bindings"][0]
    downstream = result["nodes"][1]["input_bindings"][0]
    assert output["relative_uri"].endswith("produce-records.parquet")
    assert downstream["source_node"] == "produce"
    assert downstream["relative_uri"] == output["relative_uri"]


def test_runtime_application_carries_generic_appimage_contract():
    image = app("generic", [{"name": "source", "formats": ["json"]}], [])
    result = _runtime_application(image)

    assert result["code"] == "generic"
    assert result["implementation_ref"] == "generic"
    assert result["task_input_template"] == image.task_input_template
    assert result["implementation_metadata"]["appimage"]["io_schema"] == image.io_schema
    assert result["implementation_metadata"]["appimage"]["parameter_schema"] == image.parameter_schema
    assert result["implementation_metadata"]["appimage"]["operations"] == ["process"]
    assert result["implementation_metadata"]["appimage"]["registry_source"] == "third_party"
    assert result["implementation_metadata"]["input_format"] == "json"


def test_runtime_application_separates_business_code_from_appimage_reference():
    image = app("generic-image", [{"name": "source", "formats": ["json"]}], [])

    result = _runtime_application(image, "generic-business-application", "2.0.0")

    assert result["code"] == "generic-business-application"
    assert result["version"] == "2.0.0"
    assert result["implementation_ref"] == "generic-image"


def test_application_binding_keeps_contract_environment_separate_from_connector_capability():
    image = app("bpsi-brpc-image", [], [])
    image.capability = "psi"
    application = SimpleNamespace(
        code="psi-application", version="1.0.0", status="published",
        execution_env_code="0601",
    )
    binding = SimpleNamespace(
        application_code=application.code,
        capability_requirements=["psi"],
    )

    class Database:
        def scalars(self, _statement):
            return [binding]

        def get(self, _model, key):
            return application if key == application.code else None

    contract = SimpleNamespace(document={
        "contractPolicies": [{
            "policyType": "permission",
            "actions": ["process"],
            "constraints": [{
                "constraintName": "application", "constraintOperator": "isA",
                "constraintValue": [application.code],
            }, {
                "constraintName": "executionEnv", "constraintOperator": "isA",
                "constraintValue": "0601",
            }],
            "policyExpansion": {"applicationExecution": {"allowedAppImages": [image.name]}},
        }],
    })

    code, version, execution_env, requirements = _resolve_application_contract(Database(), contract, image)

    assert (code, version) == ("psi-application", "1.0.0")
    assert execution_env == "0601"
    assert requirements == ["psi"]


def test_incompatible_implicit_binding_uses_contract_environment_and_appimage_capability():
    image = app("bpsi-brpc-image", [], [])
    image.capability = "PSI"
    incompatible_application = SimpleNamespace(
        code="bonfire-psi", version="1.0.0", status="published",
        execution_env_code="psi",
    )
    binding = SimpleNamespace(
        application_code=incompatible_application.code,
        capability_requirements=["PSI"],
    )

    class Database:
        def scalars(self, _statement):
            return [binding]

        def get(self, _model, key):
            return incompatible_application if key == incompatible_application.code else None

    contract = SimpleNamespace(document={
        "contractPolicies": [{
            "policyType": "permission",
            "actions": ["process"],
            "constraints": [{
                "constraintName": "executionEnv", "constraintOperator": "isA",
                "constraintValue": "0601",
            }],
            "policyExpansion": {"applicationExecution": {}},
        }],
    })

    code, version, execution_env, requirements = _resolve_application_contract(
        Database(), contract, image,
    )

    assert (code, version) == ("bpsi-brpc-image", "1")
    assert execution_env == "0601"
    assert requirements == ["PSI"]


def test_output_path_templates_are_workspace_scoped_and_keep_companion_names():
    image=app('producer',[],[
        {'name':'manifest','formats':['json'],'path_template':'projects/{{project.id}}/{{run.id}}/{{task.id}}/model/manifest.json'},
        {'name':'bytes','formats':['bin'],'path_template':'projects/{{project.id}}/{{run.id}}/{{task.id}}/model/parameters.bin'}])
    workflow={'nodes':[{'id':'share','app_image':'producer','output_bindings':[{'port':'manifest','domain_id':'a'},{'port':'bytes','domain_id':'a'}]}]}
    result=_runtime_workflow(workflow,{'producer':image},'project','run')
    assert [b['relative_uri'] for b in result['nodes'][0]['output_bindings']]==['projects/project/run/share/model/manifest.json','projects/project/run/share/model/parameters.bin']


def test_output_path_templates_reject_escape_variables_and_same_domain_collision():
    import pytest
    from app.services.application_template import output_path,TemplateError
    from app.services.project import ProjectError
    for path in ('/projects/{{project.id}}/{{run.id}}/x','projects/{{project.id}}/{{run.id}}/../x','projects/{{project.id}}/{{run.id}}/x\x00','projects/{{project.id}}/{{run.id}}/{{parameters.path}}','projects/other/{{run.id}}/x'):
        with pytest.raises(TemplateError):output_path(path,'project','run','task','port')
    outputs=[{'name':name,'formats':['bin'],'path_template':'projects/{{project.id}}/{{run.id}}/same.bin'} for name in ['a','b']]
    image=app('producer',[],outputs)
    workflow={'nodes':[{'id':'share','app_image':'producer','output_bindings':[{'port':'a','domain_id':'owner'},{'port':'b','domain_id':'owner'}]}]}
    with pytest.raises(ProjectError,match='重复输出'):_runtime_workflow(workflow,{'producer':image},'project','run')
    workflow['nodes'][0]['output_bindings'][1]['domain_id']='other'
    assert _runtime_workflow(workflow,{'producer':image},'project','run')
