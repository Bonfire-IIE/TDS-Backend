"""Health checks for dependencies required by the center platform."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import redis_client
from app.core.config import settings

router = APIRouter(tags=["health"])


def _check(fn) -> dict:
    try:
        fn()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 — 汇总各依赖状态，不中断
        return {"ok": False, "error": str(e)[:200]}


def _services() -> dict:
    return {
        "database": _check(lambda: engine.connect().execute(text("SELECT 1")).close()),
        "redis": _check(lambda: redis_client.ping()),
    }


@router.get("/health/live")
def live() -> dict:
    return {"code": 0, "message": "ok", "data": {"status": "up"}}


@router.get("/health/ready")
def ready():
    services = _services()
    ok = all(s["ok"] for s in services.values())
    payload = {"code": 0, "message": "ok" if ok else "degraded", "data": {"status": "up" if ok else "degraded", "services": services}}
    return payload if ok else JSONResponse(status_code=503, content=payload)


@router.get("/health")
def health() -> dict:
    services = _services()
    ok = all(s["ok"] for s in services.values())
    return {"code": 0, "message": "ok" if ok else "degraded", "data": {"status": "up" if ok else "degraded", "services": services}}


@router.get("/health/config")
def config_health() -> dict:
    """Return non-secret deployment configuration status for bootstrap/diagnostics."""
    return {"code": 0, "message": "ok", "data": {
        "database_configured": bool(settings.database_url),
        "redis_configured": bool(settings.redis_url),
        "keycloak_configured": bool(settings.keycloak_base_url),
        "opa_configured": bool(settings.opa_url),
        "rekor_configured": bool(settings.rekor_url),
        "privacy_compute_gateway_mode": "connector-local",
        "platform_registry_configured": bool(settings.platform_registry_enabled and settings.platform_registry and settings.platform_registry_project),
    }}
