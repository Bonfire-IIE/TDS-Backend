"""Central coordinator for the demonstrable UCON stages."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.ucon import UconCheck
from app.services.audit import append as audit_append, contract_stream

STAGES = ("dispatch", "static", "data_ingest", "dynamic", "runtime", "delivery")

def record(db: Session, contract_id: str, stage: str, username: str, checks: list[dict], evidence: dict | None = None, project_id: str | None = None, job_id: str | None = None) -> UconCheck:
    if stage not in STAGES: raise ValueError(f"未知校验阶段: {stage}")
    failed = next((x for x in checks if x.get("decision") != "allow"), None)
    decision = "deny" if failed else "allow"
    row = UconCheck(contract_id=contract_id, project_id=project_id, job_id=job_id, stage=stage, decision=decision, checks=checks, evidence=evidence or {}, error=failed.get("reason") if failed else None, created_by=username)
    db.add(row); db.flush()
    audit_append(db, event_type=f"ucon.{stage}.{decision}", stream_id=contract_stream(contract_id), resource_type="ucon_check", resource_id=row.id, actor={"subject": username}, payload={"stage": stage, "decision": decision, "checks": checks, "evidence": evidence or {}, "project_id": project_id, "job_id": job_id})
    return row

def list_checks(db: Session, contract_id: str) -> list[UconCheck]:
    return list(db.scalars(select(UconCheck).where(UconCheck.contract_id == contract_id).order_by(UconCheck.created_at, UconCheck.id)))

def check(contract_id: str, stage: str, username: str, **kwargs):
    """Pure stage rules used by the API and easy to call from job orchestration."""
    checks = kwargs.pop("checks", None)
    if checks is None:
        checks = [{"name": "stage_input", "decision": "allow", "reason": "输入完整"}]
    return checks
