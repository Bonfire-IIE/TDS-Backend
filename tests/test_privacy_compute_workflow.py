import pytest

from app.services.privacy_compute import PrivacyComputeError, _single_application_workflow


def metadata(inputs=None, outputs=None):
    return {
        "provider_role": "left",
        "consumer_role": "right",
        "task_alias": "compute",
        "appimage": {
            "name": "generic-image",
            "io_schema": {
                "inputs": inputs or [
                    {"name": "source_a", "role": "provider"},
                    {"name": "source_b", "role": "consumer"},
                ],
                "outputs": outputs or [{"name": "result", "formats": ["parquet"]}],
            },
        },
    }


def test_single_application_workflow_uses_registered_contract_without_app_specific_names():
    result = _single_application_workflow(
        metadata(), "connector-a", "connector-b", "resource-a", "resource-b", {"threshold": 5}
    )

    node = result["nodes"][0]
    assert node["app_image"] == "generic-image"
    assert node["parties"] == [
        {"connector_id": "connector-a", "role": "left"},
        {"connector_id": "connector-b", "role": "right"},
    ]
    assert node["input_bindings"] == [
        {"port": "source_a", "connector_id": "connector-a", "domaindata_id": "resource-a"},
        {"port": "source_b", "connector_id": "connector-b", "domaindata_id": "resource-b"},
    ]
    assert node["output_bindings"] == [{"port": "result", "format": "parquet"}]
    assert node["parameters"] == {"threshold": 5}


def test_single_application_workflow_rejects_unowned_input_port():
    with pytest.raises(PrivacyComputeError, match="provider/consumer"):
        _single_application_workflow(
            metadata(inputs=[{"name": "source", "role": "unknown"}]),
            "connector-a", "connector-b", "resource-a", "resource-b", {},
        )
