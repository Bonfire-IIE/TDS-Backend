import pytest
from app.core.config import settings
from app.services import execution_dispatch
from app.services.execution_dispatch import DispatchError, dispatch_run


def request() -> dict:
    return {
        "provider_connector_id": "provider",
        "consumer_connector_id": "consumer",
        "dispatch_connector_id": "consumer",
        "provider_connector_endpoint": "http://provider.example:8100",
        "consumer_connector_endpoint": "https://consumer.example:8100",
    }


def test_center_coordinates_both_connectors_before_single_job_submission(monkeypatch):
    calls = []

    def post(endpoint, run_id, connector_id, action, body, timeout=None):
        calls.append((connector_id, action, body))
        if action == "identity":
            return {"connector_id": connector_id, "domain_id": "domain-" + connector_id, "cert": "pem"}
        if action == "prepare":
            return {"run_id": run_id, "connector_id": connector_id, "manifests": []}
        if action == "execute":
            return {"status": "running", "external_run_ref": "kuscia-run"}
        return {"status": "succeeded", "external_run_ref": "kuscia-run"}

    monkeypatch.setattr(execution_dispatch, "_post", post)
    monkeypatch.setattr(execution_dispatch.time, "sleep", lambda _seconds: None)

    result = dispatch_run("run-1", request())

    assert [(connector, action) for connector, action, _ in calls] == [
        ("provider", "identity"), ("consumer", "identity"),
        ("provider", "prepare"), ("consumer", "prepare"),
        ("consumer", "execute"), ("consumer", "sync"),
    ]
    provider_prepare = calls[2][2]
    consumer_prepare = calls[3][2]
    execute = calls[4][2]
    assert provider_prepare["peer_identity"]["connector_id"] == "consumer"
    assert consumer_prepare["peer_identity"]["connector_id"] == "provider"
    assert execute["peer_prepared"]["connector_id"] == "provider"
    assert result["status"] == "succeeded"


def test_polling_timeout_preserves_submitted_job_for_connector_recovery(monkeypatch):
    clock = iter([0.0, 0.0, 1.0])

    def post(_endpoint, run_id, connector_id, action, _body, timeout=None):
        if action == "identity":
            return {"connector_id": connector_id, "domain_id": "domain-" + connector_id, "cert": "pem"}
        if action == "prepare":
            return {"run_id": run_id, "connector_id": connector_id, "manifests": []}
        if action == "execute":
            return {"status": "running", "external_run_ref": "kuscia-run"}
        raise DispatchError(connector_id, "temporary network failure", retryable=True)

    monkeypatch.setattr(execution_dispatch, "_post", post)
    monkeypatch.setattr(execution_dispatch.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(execution_dispatch.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(settings, "execution_dispatch_timeout_seconds", 0.5)

    result = dispatch_run("run-1", request())

    assert result == {
        "status": "running",
        "external_run_ref": "kuscia-run",
        "polling_deferred": True,
    }


@pytest.fixture(autouse=True)
def legacy_dispatch_mode(monkeypatch):
    monkeypatch.setattr(settings, 'pets_scheduler_mode', 'autonomy')
