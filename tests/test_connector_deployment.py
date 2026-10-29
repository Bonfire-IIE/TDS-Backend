from app.core.config import settings
from app.services.connector import connector_compose, deployment_instructions


def test_docker_compose_deployment_is_persistent_and_verifiable(monkeypatch) -> None:
    secret = "private-center-dispatch-credential-" + "a" * 32
    monkeypatch.setattr(settings, "execution_dispatch_secret", secret)
    result = deployment_instructions("linux", "docker-compose", "amd64", "latest")

    commands = result["commands"]
    assert "cat > .env <<EOF" in commands
    assert f"PLATFORM_API_BASE={settings.connector_platform_api_public_url}" in commands
    assert "BONFIRE_EXECUTION_DISPATCH_SECRET=\n" in commands
    assert secret not in str(result)
    assert "chmod 600 .env" in commands
    assert "docker compose up -d --wait --wait-timeout 180" in commands
    assert "curl --noproxy '*' -fsS http://127.0.0.1:8100/health" in commands


def test_connector_compose_contains_portal_and_dedicated_seatunnel() -> None:
    payload = connector_compose("latest")

    assert "services:\n  portal:" in payload
    assert "\n  seatunnel:" in payload
    assert "BONFIRE_EXECUTION_DISPATCH_SECRET:" in payload
    assert "SEATUNNEL_API_BASE: http://seatunnel:5801" in payload
    assert "PORTAL_DATA_DIR: /state" in payload
    assert "STORAGE_ROOT: /data" in payload
    assert "connector-state:/state" in payload
    assert "connector-data:/data" in payload
    assert "connector-data:/connectors/source:ro" in payload
    assert "connector-state:/connectors/source" not in payload
    assert "connector-staging:/var/lib/bonfire/staging" in payload
    assert 'test: ["CMD", "python", "-c"' in payload
    assert "runtime/server/dist" not in payload
    assert 'test: ["CMD", "node"' not in payload
    assert "healthcheck:" in payload
    assert "28081" not in payload
    assert "kuscia:" not in payload.lower()
