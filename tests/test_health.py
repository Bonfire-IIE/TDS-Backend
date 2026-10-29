from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.routers import health


def test_live_reports_process_up() -> None:
    assert health.live() == {"code": 0, "message": "ok", "data": {"status": "up"}}


def test_ready_returns_503_when_a_required_dependency_is_down(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "_services",
        lambda: {"database": {"ok": True}, "redis": {"ok": False, "error": "unreachable"}},
    )

    response = health.ready()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_ready_returns_payload_when_dependencies_are_up(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "_services",
        lambda: {"database": {"ok": True}, "redis": {"ok": True}},
    )

    response = health.ready()

    assert isinstance(response, dict)
    assert response["data"]["status"] == "up"


def test_https_mode_keeps_health_probes_available_over_cluster_http(monkeypatch) -> None:
    monkeypatch.setattr(settings, "transport_mode", "https")
    monkeypatch.setattr(settings, "require_https", False)
    client = TestClient(app)

    assert client.get("/api/v1/health/live").status_code == 200
    assert client.get("/").status_code == 426
