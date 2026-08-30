from types import SimpleNamespace

import pytest

from app.services.usage import UsageError, _enforce_obligations, compile_contract, explain_denial


def contract(policies):
    return SimpleNamespace(
        contract_id="contract-1", status="filed", product_id="product-1",
        provider_connector_id="provider-1", consumer_connector_id="consumer-1",
        contract_hash="hash", policies=policies, allowed_appimages=["app-a"],
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
    assert result["allowed_appimages"] == {"app-a": True}


def test_obligations_require_every_appimage_capability():
    apps = [{"app_image": "safe-app", "uc_capabilities": ["ephemeral", "watermark"], "operations": ["process"]}]
    assert _enforce_obligations(apps, ["ephemeral", "watermark"]) == {
        "ephemeral": "enforced_by_appimage", "watermark": "enforced_by_appimage",
    }
    with pytest.raises(UsageError, match="无法强制执行合约义务"):
        _enforce_obligations(apps, ["no_export"])


def test_no_export_obligation_conflicts_with_export_operation():
    apps = [{"app_image": "bad-app", "uc_capabilities": ["no_export"], "operations": ["process", "export"]}]
    with pytest.raises(UsageError, match="no_export 与 export 操作冲突"):
        _enforce_obligations(apps, ["no_export"])


def test_compile_contract_rejects_invalid_time():
    with pytest.raises(UsageError, match="无效的 time_window"):
        compile_contract(contract([{
            "type": "allow", "actions": ["process"],
            "constraints": {"time_window": {"from": "not-a-time"}},
        }]))


def test_explain_denial_reports_expired_window_instead_of_missing_action():
    c = contract([{
        "type": "allow", "actions": ["process"],
        "constraints": {
            "time_window": {"from": "2026-08-01T00:00:00Z", "to": "2026-08-08T00:00:00Z"},
            "count": 5, "exec_env": "mpc",
        },
    }])
    assert explain_denial(c, "consumer-1", "process", "mpc", 1786579200, 0) == "授权时间窗口已结束"


def test_explain_denial_distinguishes_action_environment_and_counter():
    c = contract([{
        "type": "allow", "actions": ["process"],
        "constraints": {"count": 2, "exec_env": "tee"},
    }])
    assert explain_denial(c, "consumer-1", "read", "mpc", 1786579200, 0) == "合约未授权操作 read"
    reason = explain_denial(c, "consumer-1", "process", "mpc", 1786579200, 2)
    assert "执行环境不匹配" in reason
    assert "使用次数已耗尽" in reason
