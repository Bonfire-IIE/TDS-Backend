from types import SimpleNamespace

from app.routers import kuscia_masters
from app.schemas.kuscia_master import KusciaMasterDeployGuide
from app.integrations import kuscia


def test_deploy_script_contains_master_bootstrap(monkeypatch):
    monkeypatch.setattr(kuscia_masters.settings, "kuscia_image", "example/kuscia:1.2")
    body = KusciaMasterDeployGuide(
        domain_id="bonfire-master",
        deployment_ip="10.2.0.11",
        gateway_port=18080,
        api_port=18081,
    )

    result = kuscia_masters.onboarding_deploy_script(body, {})["data"]

    assert "kuscia init --mode master" in result["commands"]
    assert "-p 18080 -k 18081" in result["commands"]
    assert "kuscia-master-certs" in result["commands"]
    assert result["api_endpoint"] == "https://10.2.0.11:18081"
    assert result["deploy_endpoint"] == "https://10.2.0.11:18080"


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _Db:
    def __init__(self, value):
        self.value = value

    def scalars(self, _stmt):
        return _ScalarResult(self.value)


def test_onboarding_state_missing_master():
    result = kuscia_masters.onboarding_state({}, _Db(None))["data"]
    assert result == {"configured": False, "completed": False, "master": None}


def test_onboarding_state_uses_shared_master_record(monkeypatch):
    master = SimpleNamespace(status="connected")
    monkeypatch.setattr(
        kuscia_masters.KusciaMasterOut,
        "model_validate",
        lambda value: {"id": "master-1", "status": value.status},
    )

    result = kuscia_masters.onboarding_state({}, _Db(master))["data"]

    assert result["configured"] is True
    assert result["completed"] is True
    assert result["master"]["id"] == "master-1"


def test_runtime_client_uses_database_master(monkeypatch):
    master = SimpleNamespace(
        scheme="https", deployment_ip="10.2.0.11", api_port=18081,
        credential_ref="file:/secure/master-1",
    )

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def scalars(self, _stmt): return _ScalarResult(master)

    monkeypatch.setattr("app.core.db.SessionLocal", lambda: Session())
    monkeypatch.setattr(
        kuscia, "KusciaClient",
        lambda endpoint, cert_dir: {"endpoint": endpoint, "cert_dir": cert_dir},
    )

    client = kuscia.get_kuscia_client()

    assert client == {
        "endpoint": "https://10.2.0.11:18081",
        "cert_dir": "/secure/master-1",
    }


def test_connector_endpoint_uses_database_deploy_endpoint(monkeypatch):
    master = SimpleNamespace(
        deploy_endpoint="https://49.232.11.145:18080",
        deployment_ip="10.2.0.11",
    )

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def scalars(self, _stmt): return _ScalarResult(master)

    monkeypatch.setattr("app.core.db.SessionLocal", lambda: Session())

    assert kuscia.get_kuscia_master_deploy_endpoint() == "https://49.232.11.145:18080"
