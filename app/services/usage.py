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
from app.services.audit import append as audit_append, contract_stream
from app.services.standard_contract import info as contract_info, subject as contract_subject, execution_nodes, allowed_app_images, allowed_applications, legacy_policy_input


class UsageError(Exception):
    def __init__(self, message: str, status_code: int = 403, code: str = "USAGE_DENIED", diagnostic: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.diagnostic = diagnostic


def _normalize_exec_env(value: object) -> str:
    """Return the canonical identifier used by contracts, AppImages, and OPA."""
    return str(value or "").strip().casefold()


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
    document = contract.document
    for index, source in enumerate(legacy_policy_input(document)):
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
            compiled_constraints["exec_env"] = _normalize_exec_env(constraints["exec_env"])
        policies.append({
            "id": f"{contract.contract_id}:{index + 1}",
            "effect": source.get("effect"),
            "actions": {action: True for action in source.get("actions", [])},
            "constraints": compiled_constraints,
            "obligations": source.get("obligations", []),
        })
    permitted_applications = list(dict.fromkeys(
        allowed_applications(document) + allowed_app_images(document)
    ))
    return {
        "contract_id": contract.contract_id,
        "status": contract_info(document)["contractStatus"],
        "product_id": contract_subject(document)["dataProductId"],
        "provider_connector_id": execution_nodes(document)["providerNodeId"],
        "consumer_connector_id": execution_nodes(document)["consumerNodeId"],
        "contract_hash": contract.document_hash,
        "allowed_applications": {code: True for code in permitted_applications},
        "policies": policies,
    }


def _enforce_obligations(apps: list[dict], obligations: list[str]) -> dict:
    """PEP enforcement: every data-processing AppImage must advertise required controls."""
    required = list(dict.fromkeys(obligations))
    missing: dict[str, list[str]] = {}
    for app in apps:
        capabilities = set(app.get("uc_capabilities") or [])
        absent = [item for item in required if item not in capabilities]
        if absent:
            missing[app["application_code"]] = absent
        operations = set(app.get("operations") or [])
        if "no_download" in required and "download" in operations:
            missing.setdefault(app["application_code"], []).append("no_download 与 download 操作冲突")
        if "no_export" in required and "export" in operations:
            missing.setdefault(app["application_code"], []).append("no_export 与 export 操作冲突")
    if missing:
        detail = "；".join(f"{name}: {', '.join(items)}" for name, items in missing.items())
        raise UsageError(f"应用无法强制执行合约义务：{detail}", 403, "OBLIGATION_UNSUPPORTED")
    return {item: "enforced_by_appimage" for item in required}


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
    action: str, exec_env: str, application_code: str,
) -> UsageRecord:
    """决策并持久化预占；调用方必须随后 consume 或 release。"""
    exec_env = _normalize_exec_env(exec_env)
    counter = _locked_counter(db, contract.contract_id, action)
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    context = {
        "now": int(now.timestamp()),
        "used_count": counter.used_count + counter.reserved_count,
        "exec_env": exec_env, "application_code": application_code,
    }
    decision_input = {
        "contract_id": contract.contract_id,
        "subject": {"username": username, "connector_id": connector_id},
        "action": action,
        "resource": {"product_id": contract_subject(contract.document)["dataProductId"], "application_code": application_code},
        "context": context,
    }
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        decision = client.decide(decision_input)
    except OPAError as exc:
        db.rollback()
        raise UsageError(str(exc), 503, getattr(exc, "code", "OPA_ERROR"), getattr(exc, "diagnostic", None)) from exc

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
        audit_append(db, event_type="usage.decision.denied", stream_id=contract_stream(contract.contract_id), resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"contract_id": contract.contract_id, "action": action, "reason": record.reason, "decision": record.decision, "usage_record_id": request_id})
        db.commit()
        raise UsageError(record.reason or "数字合约策略拒绝本次使用", 403)
    counter.reserved_count += 1
    audit_append(db, event_type="usage.reserved", stream_id=contract_stream(contract.contract_id), resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"contract_id": contract.contract_id, "action": action, "usage_record_id": request_id, "application_code": application_code})
    db.commit()
    db.refresh(record)
    return record


def authorize_and_reserve_workflow(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    action: str, apps: list[dict],
) -> UsageRecord:
    """一次工作流运行的统一使用控制：逐 App 决策，任一被拒即整体拒绝。

    apps: [{"exec_env": <capability>, "application_code": <code>}, ...]
    锁计数器一次、发布合约一次；全部允许才建**一条** reserved 记录并预占 1 次
    （保证“一次运行=消费 1 次”）。调用方随后须 consume 或 release。
    """
    counter = _locked_counter(db, contract.contract_id, action)
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    used = counter.used_count + counter.reserved_count
    last_decision: dict = {}
    matched_policy_ids: list[str] = []
    obligations: list[str] = []
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        for app in apps:
            exec_env = _normalize_exec_env(app["exec_env"])
            context = {
                "now": int(now.timestamp()), "used_count": used,
                "exec_env": exec_env, "application_code": app["application_code"],
            }
            decision_input = {
                "contract_id": contract.contract_id,
                "subject": {"username": username, "connector_id": connector_id},
                "action": action,
                "resource": {"product_id": contract_subject(contract.document)["dataProductId"], "application_code": app["application_code"]},
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
                audit_append(db, event_type="usage.decision.denied", stream_id=contract_stream(contract.contract_id), resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"contract_id": contract.contract_id, "action": action, "reason": record.reason, "decision": record.decision, "usage_record_id": request_id})
                db.commit()
                raise UsageError(
                    record.reason or f"数字合约策略拒绝应用 {app['application_code']}", 403
                )
            matched_policy_ids.extend(last_decision.get("matched_policy_ids", []))
            obligations.extend(last_decision.get("obligations", []))
    except OPAError as exc:
        db.rollback()
        raise UsageError(str(exc), 503, getattr(exc, "code", "OPA_ERROR"), getattr(exc, "diagnostic", None)) from exc

    obligations = list(dict.fromkeys(obligations))
    obligation_status = _enforce_obligations(apps, obligations)
    context = {
        "now": int(now.timestamp()), "used_count": used,
        "exec_env": ",".join(_normalize_exec_env(a["exec_env"]) for a in apps),
        "application_code": ",".join(a["application_code"] for a in apps),
    }
    record = UsageRecord(
        request_id=request_id, contract_id=contract.contract_id,
        connector_id=connector_id, username=username, action=action,
        decision=last_decision.get("decision", "allow"), lifecycle="reserved",
        reason=last_decision.get("reason"),
        matched_policy_ids=list(dict.fromkeys(matched_policy_ids)), context=context,
        obligations=obligations, obligation_status=obligation_status,
    )
    db.add(record)
    counter.reserved_count += 1
    audit_append(db, event_type="usage.reserved", stream_id=contract_stream(contract.contract_id), resource_type="usage_record", resource_id=request_id, actor={"subject": username}, payload={"contract_id": contract.contract_id, "action": action, "usage_record_id": request_id, "application_code": context["application_code"]})
    db.commit()
    db.refresh(record)
    return record


def authorize_and_reserve_actions(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    apps: list[dict],
) -> list[UsageRecord]:
    """Reserve each distinct declared action once per workflow; roll back prior reservations on denial."""
    by_action: dict[str, list[dict]] = {}
    for app in apps:
        for action in list(dict.fromkeys(app.get("operations") or ["process"])):
            by_action.setdefault(action, []).append(app)
    records: list[UsageRecord] = []
    try:
        for action, action_apps in by_action.items():
            records.append(authorize_and_reserve_workflow(
                db, contract, username, connector_id, action, action_apps,
            ))
        return records
    except Exception:
        for record in records:
            release(db, record.id, "同一运行的其他操作未通过准入")
        raise


def _consume_record(db: Session, record_id: str, job_id: str) -> None:
    record = db.get(UsageRecord, record_id)
    if not record or record.lifecycle != "reserved":
        raise UsageError("使用预占不存在或状态异常", 409)
    counter = _locked_counter(db, record.contract_id, record.action)
    counter.reserved_count = max(0, counter.reserved_count - 1)
    counter.used_count += 1
    record.lifecycle = "consumed"
    record.job_id = job_id
    audit_append(db, event_type="usage.consumed", stream_id=contract_stream(record.contract_id), resource_type="usage_record", resource_id=record.request_id, actor={"subject": record.username}, payload={"contract_id": record.contract_id, "job_id": job_id, "usage_record_id": record.request_id})
    return None


def consume(db: Session, record_id: str, job_id: str) -> None:
    _consume_record(db, record_id, job_id)
    db.commit()


def consume_many(db: Session, records: list[UsageRecord], job_id: str) -> None:
    for record in records:
        _consume_record(db, record.id, job_id)
    db.commit()


def release(db: Session, record_id: str, reason: str) -> None:
    record = db.get(UsageRecord, record_id)
    if not record or record.lifecycle != "reserved":
        return
    counter = _locked_counter(db, record.contract_id, record.action)
    counter.reserved_count = max(0, counter.reserved_count - 1)
    record.lifecycle = "released"
    record.reason = reason
    audit_append(db, event_type="usage.released", stream_id=contract_stream(record.contract_id), resource_type="usage_record", resource_id=record.request_id, actor={"subject": record.username}, payload={"contract_id": record.contract_id, "reason": reason, "usage_record_id": record.request_id})
    db.commit()


def release_many(db: Session, records: list[UsageRecord], reason: str) -> None:
    for record in records:
        release(db, record.id, reason)


def compensate(db: Session, record_id: str, reason: str) -> bool:
    """Idempotently return one consumed count when an accepted execution ends in failure."""
    record = db.get(UsageRecord, record_id)
    if not record or record.lifecycle == "compensated":
        return False
    if record.lifecycle != "consumed":
        return False
    counter = _locked_counter(db, record.contract_id, record.action)
    counter.used_count = max(0, counter.used_count - 1)
    record.lifecycle = "compensated"
    record.reason = reason
    audit_append(db, event_type="usage.compensated", stream_id=contract_stream(record.contract_id), resource_type="usage_record", resource_id=record.request_id, actor={"subject": record.username}, payload={"contract_id": record.contract_id, "job_id": record.job_id, "action": record.action, "reason": reason, "usage_record_id": record.request_id})
    db.commit()
    return True


def compensate_many(db: Session, record_ids: list[str], reason: str) -> None:
    for record_id in list(dict.fromkeys(record_ids)):
        compensate(db, record_id, reason)


def check_operations(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    operations: list[str], exec_env: str, application_code: str,
) -> list[dict]:
    """只读符合性校验：逐个操作问 OPA 是否被合约允许，返回**被拒**的操作列表。

    不动计数器、不落记录，仅在真正预占前提供可读的拒绝原因。校验使用当前
    ``used_count + reserved_count``；真正的逐操作计数由
    :func:`authorize_and_reserve_actions` 完成。
    """
    exec_env = _normalize_exec_env(exec_env)
    try:
        client = get_opa_client()
        client.publish_contract(contract.contract_id, compile_contract(contract))
        denied: list[dict] = []
        now = int(datetime.now(timezone.utc).timestamp())
        for action in operations:
            counter = db.execute(select(UsageCounter).where(
                UsageCounter.contract_id == contract.contract_id,
                UsageCounter.action == action,
            )).scalar_one_or_none()
            used_count = (counter.used_count + counter.reserved_count) if counter else 0
            decision = client.decide({
                "contract_id": contract.contract_id,
                "subject": {"username": username, "connector_id": connector_id},
                "action": action,
                "resource": {"product_id": contract_subject(contract.document)["dataProductId"], "application_code": application_code},
                "context": {"now": now, "used_count": used_count, "exec_env": exec_env, "application_code": application_code},
            })
            if not decision.get("allowed", False):
                denied.append({
                    "action": action,
                    "reason": explain_denial(contract, connector_id, action, exec_env, now, used_count),
                    "decision": decision.get("decision"),
                    "matched_policy_ids": decision.get("matched_policy_ids", []),
                })
        return denied
    except OPAError as exc:
        raise UsageError(str(exc), 503, getattr(exc, "code", "OPA_ERROR"), getattr(exc, "diagnostic", None)) from exc


def explain_denial(contract: DigitalContract, connector_id: str, action: str,
                   exec_env: str, now: int, used_count: int) -> str:
    """在不暴露策略正文的前提下，将 OPA default-deny 解释为可操作原因。"""
    exec_env = _normalize_exec_env(exec_env)
    if contract_info(contract.document)["contractStatus"] != "filed":
        return "合约尚未备案或已失效"
    node_id = execution_nodes(contract.document)["consumerNodeId"]
    if connector_id != node_id:
        return "当前连接器不是该合约约定的用数方"
    candidates = [p for p in legacy_policy_input(contract.document)
                  if p.get("effect") == "allow" and action in (p.get("actions") or [])]
    if not candidates:
        return f"合约未授权操作 {action}"
    all_failures: list[str] = []
    for policy in candidates:
        failures: list[str] = []
        constraints = policy.get("constraints") or {}
        window = constraints.get("time_window") or {}
        start, end = _parse_time(window.get("from")), _parse_time(window.get("to"))
        if start is not None and now < start:
            failures.append("授权时间尚未开始")
        elif end is not None and now > end:
            failures.append("授权时间窗口已结束")
        required_env = _normalize_exec_env(constraints.get("exec_env"))
        if required_env and required_env != exec_env:
            failures.append(f"执行环境不匹配（要求 {required_env}）")
        limit = constraints.get("count")
        if limit is not None and used_count >= int(limit):
            failures.append("合约允许的使用次数已耗尽")
        if not failures:
            return "策略约束未满足"
        all_failures.extend(failures)
    return "；".join(dict.fromkeys(all_failures))


def preflight(
    db: Session, contract: DigitalContract, username: str, connector_id: str,
    action: str, exec_env: str, application_code: str,
) -> dict:
    """无副作用预检；结果仅用于展示，真正提交时仍须重新决策和预占。"""
    exec_env = _normalize_exec_env(exec_env)
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
        "resource": {"product_id": contract_subject(contract.document)["dataProductId"], "application_code": application_code},
        "context": {
            "now": int(datetime.now(timezone.utc).timestamp()),
            "used_count": used + reserved, "exec_env": exec_env, "application_code": application_code,
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
