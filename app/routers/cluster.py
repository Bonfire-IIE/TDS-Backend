"""集群状态：经 KusciaAPI 汇总节点信息，供前端「集群状态」页展示。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.integrations.kuscia import KusciaError, get_kuscia_client
from app.models.connector import Connector

router = APIRouter(prefix="/cluster", tags=["cluster"])


@router.get("/status")
def cluster_status(db: Session = Depends(get_db)) -> dict:
    client = get_kuscia_client()
    result: dict = {"kusciaApi": "up", "domains": []}
    domain_ids = list(db.scalars(
        select(Connector.kuscia_domain_id)
        .where(Connector.deleted_at.is_(None), Connector.status == "approved")
        .order_by(Connector.kuscia_domain_id)
    ))
    if not domain_ids:
        result["message"] = "KusciaAPI 已连接，当前没有已审批的连接器"
        return {"code": 0, "message": "ok", "data": result}
    try:
        domains = client.batch_query_domains(domain_ids)
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
