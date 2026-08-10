"""数字合约业务逻辑：发起 / 磋商 / 签署 / 备案 / 终止（哈希占位签名）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_contract_code
from app.models.connector import Connector
from app.models.contract import ContractParty, DigitalContract, NegotiationHistory
from app.models.product import DataProduct
from app.schemas.contract import ContractRequest, ProposeRequest
from app.services.audit import append as audit_append


class ContractError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _file_signed(c: DigitalContract) -> None:
    """Finalize a fully signed contract without a separate filing action."""
    c.contract_hash = _contract_hash(c)
    c.status = "filed"


# ---------- 哈希工具（占位签名，后续替换真数字签名） ----------
def _canonical(obj) -> str:
    """规范化 JSON：键排序、无多余空白，保证可复现的哈希输入。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _contract_info(c: DigitalContract) -> dict:
    """参与签名/快照的合约信息 + 当前策略。"""
    return {
        "contract_id": c.contract_id,
        "name": c.name,
        "purpose": c.purpose,
        "product_id": c.product_id,
        "provider_connector_id": c.provider_connector_id,
        "consumer_connector_id": c.consumer_connector_id,
        "mode": c.mode,
        "policies": c.policies or [],
        "allowed_appimages": c.allowed_appimages or [],
    }


def _signature_hash(c: DigitalContract, party_role: str) -> str:
    """签名占位：sha256(规范化(合约信息+policies) + party_role)。"""
    return _sha256(_canonical(_contract_info(c)) + party_role)


def _contract_hash(c: DigitalContract) -> str:
    """备案存证：对整合约（含各方签名）求 sha256。"""
    full = _contract_info(c)
    full["parties"] = sorted(
        [
            {
                "party_role": p.party_role,
                "connector_id": p.connector_id,
                "entity": p.entity,
                "signature_hash": p.signature_hash,
            }
            for p in c.parties
        ],
        key=lambda x: x["party_role"],
    )
    return _sha256(_canonical(full))


def _append_history(db: Session, c: DigitalContract, op: str, operator: str | None) -> None:
    """追加一轮协商历史，维护哈希链 curr=sha256(prev + 规范化(snapshot))。"""
    last = c.history[-1] if c.history else None
    prev_hash = last.curr_hash if last else ""
    round_no = (last.round + 1) if last else 1
    snapshot = _contract_info(c)
    curr_hash = _sha256(prev_hash + _canonical(snapshot))
    c.history.append(
        NegotiationHistory(
            round=round_no, op=op, operator=operator,
            snapshot=snapshot, prev_hash=prev_hash, curr_hash=curr_hash,
        )
    )


# ---------- 权限/归属工具 ----------
def _owns(db: Session, connector_id: str, username: str) -> bool:
    conn = db.get(Connector, connector_id)
    return bool(conn and conn.created_by == username)


def _caller_role(db: Session, c: DigitalContract, username: str) -> str | None:
    """调用者可代表的参与方角色（拥有对应连接器）。"""
    if _owns(db, c.consumer_connector_id, username):
        return "consumer"
    if _owns(db, c.provider_connector_id, username):
        return "provider"
    return None


def _require_actor(db: Session, c: DigitalContract, username: str, is_operator: bool) -> str | None:
    """校验调用者为合约相关方（供/用/运营），返回其角色（operator 可能为 None）。"""
    role = _caller_role(db, c, username)
    if role is None and not is_operator:
        raise ContractError("无权操作该合约", 403)
    return role


# ---------- 生成合约码 ----------
def _new_contract_id(db: Session) -> str:
    for _ in range(5):
        code = gen_contract_code(
            settings.tds_default_subject_code, settings.tds_default_region_industry
        )
        if not db.get(DigitalContract, code):
            return code
    raise ContractError("合约码分配失败，请重试", 500)


# ---------- 用例 ----------
def request(
    db: Session, product_id: str, username: str, is_operator: bool, body: ContractRequest
) -> DigitalContract:
    product = db.get(DataProduct, product_id)
    if not product:
        raise ContractError("产品不存在", 404)
    if product.status != "listed":
        raise ContractError("产品未上架，无法申请", 409)

    consumer = db.get(Connector, body.consumer_connector_id)
    if not consumer:
        raise ContractError("用数方连接器不存在", 404)
    if not is_operator and consumer.created_by != username:
        raise ContractError("只能使用自己的连接器申请", 403)
    if consumer.status != "approved":
        raise ContractError("用数方连接器未审批通过", 409)

    provider = db.get(Connector, product.provider_connector_id)
    provider_entity = provider.created_by if provider else None
    baseline = product.baseline_policies or []

    c = DigitalContract(
        contract_id=_new_contract_id(db),
        name=product.name,
        abstract=product.description,
        purpose=body.purpose,
        product_id=product.id,
        provider_connector_id=product.provider_connector_id,
        consumer_connector_id=consumer.id,
        mode=product.transaction_mode,
        created_by=username,
    )
    c.parties = [
        ContractParty(party_role="provider", connector_id=product.provider_connector_id, entity=provider_entity),
        ContractParty(party_role="consumer", connector_id=consumer.id, entity=username),
    ]

    if product.transaction_mode == "accept":
        # 提案-接受：打字确认即视为用数方签署，供数方基准=常设要约
        if body.confirm != product.name:
            raise ContractError("确认串不匹配（需输入产品名称完成打字确认）", 400)
        if not body.purpose:
            raise ContractError("使用目的必填", 400)
        c.policies = baseline
        c.status = "signed"
        now = datetime.utcnow()
        for p in c.parties:
            p.signature_hash = _signature_hash(c, p.party_role)
            p.signed_at = now
        _file_signed(c)
    else:
        # 提案-修订-共识：建协商态，记 round1
        c.policies = (
            [p.model_dump(by_alias=True) for p in body.policies]
            if body.policies is not None else baseline
        )
        c.allowed_appimages = list(body.allowed_appimages if body.allowed_appimages is not None else (product.allowed_appimages or []))
        c.status = "negotiating"
        _append_history(db, c, op="propose", operator=username)

    db.add(c)
    # 审计事件与合约写入同一事务，Rekor 不可用不影响业务提交。
    audit_append(db, event_type="contract.created", stream_id=f"contract:{c.contract_id}",
                 resource_type="digital_contract", resource_id=c.contract_id,
                 actor={"subject": username}, payload={"product_id": c.product_id, "provider_connector_id": c.provider_connector_id, "consumer_connector_id": c.consumer_connector_id, "mode": c.mode, "status": c.status, "contract_hash": c.contract_hash})
    db.commit()
    db.refresh(c)
    return c


def _get_or_404(db: Session, contract_id: str) -> DigitalContract:
    c = db.get(DigitalContract, contract_id)
    if not c:
        raise ContractError("合约不存在", 404)
    return c


def get(db: Session, contract_id: str, username: str, is_operator: bool) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    if not is_operator:
        if c.created_by != username and not _owns(db, c.provider_connector_id, username):
            raise ContractError("无权访问", 403)
    return c


def list_contracts(db: Session, username: str, is_operator: bool) -> list[DigitalContract]:
    stmt = select(DigitalContract).order_by(DigitalContract.created_at.desc())
    if not is_operator:
        # 我发起的，或我是供数方（拥有 provider 连接器）
        owned = db.execute(
            select(Connector.id).where(Connector.created_by == username)
        ).scalars().all()
        conds = [DigitalContract.created_by == username]
        if owned:
            conds.append(DigitalContract.provider_connector_id.in_(owned))
        stmt = stmt.where(or_(*conds))
    return list(db.execute(stmt).scalars())


def propose(
    db: Session, contract_id: str, username: str, is_operator: bool, body: ProposeRequest
) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    _require_actor(db, c, username, is_operator)
    if c.status not in ("negotiating", "signed"):
        raise ContractError(f"当前状态 {c.status} 不可提交修订", 409)

    c.policies = [p.model_dump(by_alias=True) for p in body.policies]
    if body.allowed_appimages is not None:
        c.allowed_appimages = body.allowed_appimages
    c.status = "negotiating"
    # 策略变更 → 清空双方既有签署
    for p in c.parties:
        p.signature_hash = None
        p.signed_at = None
    _append_history(db, c, op="propose", operator=username)
    audit_append(db, event_type="contract.proposed", stream_id=f"contract:{c.contract_id}", resource_type="digital_contract", resource_id=c.contract_id, actor={"subject": username}, payload={"status": c.status, "policies_hash": _sha256(_canonical(c.policies or []))})
    db.commit()
    db.refresh(c)
    return c


def sign(db: Session, contract_id: str, username: str, is_operator: bool) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    # A signature always belongs to the connector owner; operators cannot sign for a party.
    roles: set[str] = set()
    if _owns(db, c.consumer_connector_id, username):
        roles.add("consumer")
    if _owns(db, c.provider_connector_id, username):
        roles.add("provider")
    if not roles:
        raise ContractError("仅合约参与方可签署", 403)
    if c.status != "negotiating":
        raise ContractError(f"当前状态 {c.status} 不可签署", 409)

    # 每次签署一个尚未签署、且调用者可代表的参与方
    now = datetime.utcnow()
    signed = False
    for p in c.parties:
        if p.party_role in roles and not p.signature_hash:
            p.signature_hash = _signature_hash(c, p.party_role)
            p.signed_at = now
            signed = True
            break
    if not signed:
        raise ContractError("您可代表的各方均已签署", 409)
    if all(p.signature_hash for p in c.parties):
        _file_signed(c)
    audit_append(db, event_type="contract.signed", stream_id=f"contract:{c.contract_id}", resource_type="digital_contract", resource_id=c.contract_id, actor={"subject": username}, payload={"status": c.status, "signed_roles": [p.party_role for p in c.parties if p.signature_hash], "contract_hash": c.contract_hash})
    db.commit()
    db.refresh(c)
    return c


def file(db: Session, contract_id: str, username: str, is_operator: bool) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    _require_actor(db, c, username, is_operator)
    if c.status == "filed":
        return c
    if c.status != "signed":
        raise ContractError(f"当前状态 {c.status} 不可备案（需先 signed）", 409)
    _file_signed(c)
    audit_append(db, event_type="contract.filed", stream_id=f"contract:{c.contract_id}", resource_type="digital_contract", resource_id=c.contract_id, actor={"subject": username}, payload={"contract_hash": c.contract_hash, "signature_hashes": [p.signature_hash for p in c.parties]})
    db.commit()
    db.refresh(c)
    return c


def terminate(db: Session, contract_id: str, username: str, is_operator: bool) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    _require_actor(db, c, username, is_operator)
    c.status = "terminated"
    audit_append(db, event_type="contract.terminated", stream_id=f"contract:{c.contract_id}", resource_type="digital_contract", resource_id=c.contract_id, actor={"subject": username}, payload={"status": c.status})
    db.commit()
    db.refresh(c)
    return c


def reject(db: Session, contract_id: str, username: str, is_operator: bool) -> DigitalContract:
    c = _get_or_404(db, contract_id)
    _require_actor(db, c, username, is_operator)
    c.status = "rejected"
    audit_append(db, event_type="contract.rejected", stream_id=f"contract:{c.contract_id}", resource_type="digital_contract", resource_id=c.contract_id, actor={"subject": username}, payload={"status": c.status})
    db.commit()
    db.refresh(c)
    return c
