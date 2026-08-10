"""集群状态：经 KusciaAPI 汇总节点信息，供前端「集群状态」页展示。"""
from fastapi import APIRouter

from app.core.config import settings
from app.integrations.kuscia import KusciaError, get_kuscia_client

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("/status")
def cluster_status() -> dict:
    client = get_kuscia_client()
    result: dict = {"kusciaApi": "up", "domains": []}
    try:
        domains = client.batch_query_domains(settings.kuscia_domains)
        result["domains"] = [
            {
                "domainId": d.get("domain_id"),
                "role": d.get("role") or "internal",
                "nodeCount": len(d.get("node_statuses", []) or []),
            }
            for d in domains
        ]
    except KusciaError as e:
        result["kusciaApi"] = "down"
        result["error"] = str(e)[:200]
    return {"code": 0, "message": "ok", "data": result}
