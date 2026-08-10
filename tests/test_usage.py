from types import SimpleNamespace

import pytest

from app.services.usage import UsageError, compile_contract


def contract(policies):
    return SimpleNamespace(
        contract_id="contract-1", status="filed", product_id="product-1",
        provider_connector_id="provider-1", consumer_connector_id="consumer-1",
        contract_hash="hash", policies=policies,
    )


def test_compile_contract_maps_policy_to_opa_data():
    result = compile_contract(contract([{
        "type": "allow", "actions": ["process"],
        "constraints": {
            "time_window": {"from": "2026-07-01T00:00:00Z", "to": None},
            "count": 3, "exec_env": "mpc",
        },
    }]))

    policy = result["policies"][0]
    assert policy["effect"] == "allow"
    assert policy["actions"] == {"process": True}
    assert policy["constraints"]["count"] == {"max": 3}
    assert policy["constraints"]["exec_env"] == "mpc"
    assert policy["constraints"]["time_window"]["from"] == 1782864000


def test_compile_contract_rejects_invalid_time():
    with pytest.raises(UsageError, match="无效的 time_window"):
        compile_contract(contract([{
            "type": "allow", "actions": ["process"],
            "constraints": {"time_window": {"from": "not-a-time"}},
        }]))
