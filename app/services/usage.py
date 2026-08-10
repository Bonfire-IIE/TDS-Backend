"""数字合约策略编译、OPA 决策和使用次数预占。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.opa import OPAError, get_opa_client
from app.models.contract import DigitalContract
from app.models.usage import UsageCounter, UsageRecord
from app.services.audit import append as audit_append


class UsageError(Exception):
    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _parse_time(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError as exc:
        raise UsageError(f"无效的 time_window 时间: {value}", 409) from exc


def compile_contract(contract: DigitalContract) -> dict:
    """把合约业务 JSON 编译为 OPA data；Rego 保持固定，不生成合约专属代码。"""
    policies = []
    for index, source in enumerate(contract.policies or []):
        constraints = source.get("constraints") or {}
        window = constraints.get("time_window") or {}
        compiled_constraints: dict = {}
        if window:
            compiled_constraints["time_window"] = {
                "from": _parse_time(window.get("from")),
                "to": _parse_time(window.get("to")),
            }
        if constraints.get("count") is not None:
            compiled_constraints["count"] = {"max": int(constraints["count"])}
        if constraints.get("exec_env"):
            compiled_constraints["exec_env"] = constraints["exec_env"]
        policies.append({
            "id": f"{contract.contract_id}:{index + 1}",
            "effect": source.get("type"),
            "actions": {action: True for action in source.get("actions", [])},
            "constraints": compiled_constraints,
            "obligations": source.get("obligations", []),
        })
    return {
        "contract_id": contract.contract_id,
        "status": contract.status,
        "product_id": contract.product_id,
        "provider_connector_id": contract.provider_connector_id,
        "consumer_connector_id": contract.consumer_connector_id,
        "contract_hash": contract.contract_hash,
        "policies": policies,
    }


def _locked_counter(db: Session, contract_id: str, action: str) -> UsageCounter:
    stmt = select(UsageCounter).where(
        UsageCounter.contract_id == contract_id, UsageCounter.action == action
    ).with_for_update()
    counter = db.execute(stmt).scalar_one_or_none()
    if counter:
        return counter
    counter = UsageCounter(contract_id=contract_id, action=action, used_count=0)
    db.add(counter)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        counter = db.execute(stmt).scalar_one()
    return counter


def authorize_and_reserve(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    action: str, exec_env: str, app_image: str,
) -> UsageRecord:
    """决策并持久化预占；调用方必须随后 consume 或 release。"""
    counter = _locked_counter(db, contract.contract_id, action)
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    context = {
        "now": int(now.timestamp()),
        "used_count": counter.used_count + counter.reserved_count,
        "exec_env": exec_env, "app_image": app_image,
    }
    decision_input = {
        "contract_id": contract.contract_id,
        "subject": {"username": username, "connector_id": connector_id},
        "action": action,
        "resource": {"product_id": contract.product_id, "app_image": app_image},
        "context": context,
    }
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        decision = client.decide(decision_input)
    except OPAError as exc:
        db.rollback()
        raise UsageError(str(exc), 503) from exc

    record = UsageRecord(
        request_id=request_id, contract_id=contract.contract_id,
        connector_id=connector_id, username=username, action=action,
        decision=decision.get("decision", "default_deny"),
        lifecycle="reserved" if decision.get("allowed", False) else "decided",
        reason=decision.get("reason"),
        matched_policy_ids=decision.get("matched_policy_ids", []), context=context,
    )
    db.add(record)
    if not decision.get("allowed", False):
        audit_append(db, event_type="usage.decision.denied", stream_id=f"usage:{contract.contract_id}", resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"action": action, "reason": record.reason, "decision": record.decision, "usage_record_id": request_id})
        db.commit()
        raise UsageError(record.reason or "数字合约策略拒绝本次使用", 403)
    counter.reserved_count += 1
    audit_append(db, event_type="usage.reserved", stream_id=f"usage:{contract.contract_id}", resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"action": action, "usage_record_id": request_id, "app_image": app_image})
    db.commit()
    db.refresh(record)
    return record


def authorize_and_reserve_workflow(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    action: str, apps: list[dict],
) -> UsageRecord:
    """一次工作流运行的统一使用控制：逐 App 决策，任一被拒即整体拒绝。

    apps: [{"exec_env": <capability>, "app_image": <name>}, ...]
    锁计数器一次、发布合约一次；全部允许才建**一条** reserved 记录并预占 1 次
    （保证“一次运行=消费 1 次”）。调用方随后须 consume 或 release。
    """
    counter = _locked_counter(db, contract.contract_id, action)
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    used = counter.used_count + counter.reserved_count
    last_decision: dict = {}
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        for app in apps:
            context = {
                "now": int(now.timestamp()), "used_count": used,
                "exec_env": app["exec_env"], "app_image": app["app_image"],
            }
            decision_input = {
                "contract_id": contract.contract_id,
                "subject": {"username": username, "connector_id": connector_id},
                "action": action,
                "resource": {"product_id": contract.product_id, "app_image": app["app_image"]},
                "context": context,
            }
            last_decision = client.decide(decision_input)
            if not last_decision.get("allowed", False):
                record = UsageRecord(
                    request_id=request_id, contract_id=contract.contract_id,
                    connector_id=connector_id, username=username, action=action,
                    decision=last_decision.get("decision", "default_deny"),
                    lifecycle="decided", reason=last_decision.get("reason"),
                    matched_policy_ids=last_decision.get("matched_policy_ids", []),
                    context=context,
                )
                db.add(record)
                audit_append(db, event_type="usage.decision.denied", stream_id=f"usage:{contract.contract_id}", resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"action": action, "reason": record.reason, "decision": record.decision, "usage_record_id": request_id})
                db.commit()
                raise UsageError(
                    record.reason or f"数字合约策略拒绝应用 {app['app_image']}", 403
                )
    except OPAError as exc:
        db.rollback()
        raise UsageError(str(exc), 503) from exc

    context = {
        "now": int(now.timestamp()), "used_count": used,
        "exec_env": ",".join(a["exec_env"] for a in apps),
        "app_image": ",".join(a["app_image"] for a in apps),
    }
    record = UsageRecord(
        request_id=request_id, contract_id=contract.contract_id,
        connector_id=connector_id, username=username, action=action,
        decision=last_decision.get("decision", "allow"), lifecycle="reserved",
        reason=last_decision.get("reason"),
        matched_policy_ids=last_decision.get("matched_policy_ids", []), context=context,
    )
    db.add(record)
    counter.reserved_count += 1
    audit_append(db, event_type="usage.reserved", stream_id=f"usage:{contract.contract_id}", resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"action": action, "usage_record_id": request_id, "app_image": context["app_image"]})
    db.commit()
    db.refresh(record)
    return record


def consume(db: Session, record_id: str, job_id: str) -> None:
    record = db.get(UsageRecord, record_id)
    if not record or record.lifecycle != "reserved":
        raise UsageError("使用预占不存在或状态异常", 409)
    counter = _locked_counter(db, record.contract_id, record.action)
    counter.reserved_count = max(0, counter.reserved_count - 1)
    counter.used_count += 1
    record.lifecycle = "consumed"
    record.job_id = job_id
    audit_append(db, event_type="usage.consumed", stream_id=f"usage:{record.contract_id}", resource_type="usage_record", resource_id=record.request_id, actor={"subject": record.username}, payload={"job_id": job_id, "usage_record_id": record.request_id})
    db.commit()


def release(db: Session, record_id: str, reason: str) -> None:
    record = db.get(UsageRecord, record_id)
    if not record or record.lifecycle != "reserved":
        return
    counter = _locked_counter(db, record.contract_id, record.action)
    counter.reserved_count = max(0, counter.reserved_count - 1)
    record.lifecycle = "released"
    record.reason = reason
    audit_append(db, event_type="usage.released", stream_id=f"usage:{record.contract_id}", resource_type="usage_record", resource_id=record.request_id, actor={"subject": record.username}, payload={"reason": reason, "usage_record_id": record.request_id})
    db.commit()


def check_operations(
    contract: DigitalContract, username: str, connector_id: str,
    operations: list[str], exec_env: str, app_image: str,
) -> list[str]:
    """只读符合性校验：逐个操作问 OPA 是否被合约允许，返回**被拒**的操作列表。

    不动计数器、不落记录（count 仍只在 process 预留时消耗）；仅校验"该操作是否在
    合约授权范围内"。used_count 传 0——这里只判许可，不判次数。
    """
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        denied: list[str] = []
        now = int(datetime.now(timezone.utc).timestamp())
        for action in operations:
            decision = client.decide({
                "contract_id": contract.contract_id,
                "subject": {"username": username, "connector_id": connector_id},
                "action": action,
                "resource": {"product_id": contract.product_id, "app_image": app_image},
                "context": {"now": now, "used_count": 0, "exec_env": exec_env, "app_image": app_image},
            })
            if not decision.get("allowed", False):
                denied.append(action)
        return denied
    except OPAError as exc:
        raise UsageError(str(exc), 503) from exc


def preflight(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    action: str, exec_env: str, app_image: str,
) -> dict:
    """无副作用预检；结果仅用于展示，真正提交时仍须重新决策和预占。"""
    counter = db.execute(select(UsageCounter).where(
        UsageCounter.contract_id == contract.contract_id,
        UsageCounter.action == action,
    )).scalar_one_or_none()
    used = counter.used_count if counter else 0
    reserved = counter.reserved_count if counter else 0
    document = compile_contract(contract)
    decision_input = {
        "contract_id": contract.contract_id,
        "subject": {"username": username, "connector_id": connector_id},
        "action": action,
        "resource": {"product_id": contract.product_id, "app_image": app_image},
        "context": {
            "now": int(datetime.now(timezone.utc).timestamp()),
            "used_count": used + reserved, "exec_env": exec_env, "app_image": app_image,
        },
    }
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, document)
        decision = client.decide(decision_input)
    except OPAError as exc:
        raise UsageError(str(exc), 503) from exc
    limits = [
        p.get("constraints", {}).get("count", {}).get("max")
        for p in document["policies"]
        if p.get("effect") == "allow" and p.get("actions", {}).get(action)
        and p.get("constraints", {}).get("count")
    ]
    now = datetime.now(timezone.utc)
    checks: list[dict] = []
    action_policies = [p for p in document["policies"] if p.get("effect") == "allow" and p.get("actions", {}).get(action)]
    checks.append({"key": "action", "label": "允许 process 操作", "passed": bool(action_policies),
                   "detail": "命中允许策略" if action_policies else "合约没有允许 process 的策略"})
    for p in action_policies:
        c = p.get("constraints", {})
        window = c.get("time_window")
        passed = True
        detail = "未设置时间窗口"
        if window:
            start = datetime.fromtimestamp(window["from"], timezone.utc) if window.get("from") is not None else None
            end = datetime.fromtimestamp(window["to"], timezone.utc) if window.get("to") is not None else None
            passed = (start is None or now >= start) and (end is None or now <= end)
            detail = f"允许时间：{start.isoformat() if start else '不限'} 至 {end.isoformat() if end else '不限'}"
        checks.append({"key": f"time:{p['id']}", "label": "时间窗口", "passed": passed,
                       "detail": detail if passed else detail + f"；当前时间：{now.isoformat()}"})
        env = c.get("exec_env")
        passed = not env or env == exec_env
        checks.append({"key": f"env:{p['id']}", "label": "执行环境", "passed": passed,
                       "detail": f"应用能力为 {exec_env}，策略要求 {env or '不限'}"})
        limit = (c.get("count") or {}).get("max")
        passed = limit is None or used + reserved < limit
        checks.append({"key": f"count:{p['id']}", "label": "使用次数", "passed": passed,
                       "detail": f"已使用 {used} 次，预占 {reserved} 次" + (f"，上限 {limit} 次" if limit is not None else "，不限次数")})
    return {
        **decision, "used_count": used, "reserved_count": reserved,
        "max_count": min(limits) if limits else None,
        "checks": checks,
    }
