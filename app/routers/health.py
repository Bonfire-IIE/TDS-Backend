"""健康检查：DB / Redis / Kuscia 三个依赖的连通性。"""
from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import redis_client
from app.integrations.kuscia import get_kuscia_client, kuscia_master_configured
from app.core.config import settings

router = APIRouter(tags=["health"])


def _check(fn) -> dict:
    try:
        fn()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 — 汇总各依赖状态，不中断
        return {"ok": False, "error": str(e)[:200]}


@router.get("/health")
def health() -> dict:
    services = {
        "database": _check(lambda: engine.connect().execute(text("SELECT 1")).close()),
        "redis": _check(lambda: redis_client.ping()),
        "kuscia": _check(lambda: get_kuscia_client().ping()),
    }
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
        "kuscia_configured": kuscia_master_configured(),
        "platform_registry_configured": bool(settings.platform_registry_enabled and settings.platform_registry and settings.platform_registry_project),
    }}
