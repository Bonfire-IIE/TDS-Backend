"""标准 TC609 数字合约生命周期服务。"""
from __future__ import annotations

import hashlib, json, copy
from datetime import datetime, timezone
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_contract_code
from app.models.connector import Connector
from app.models.contract import DigitalContract, DigitalContractVersion
from app.models.product import DataProduct
from app.models.signing import UserSigningKey
from app.schemas.contract import ContractRequest, ProposeRequest
from app.services.audit import append as audit_append, contract_stream
from app.services.signing import sign as sign_payload, verify as verify_payload
from app.services.standard_contract import validate_document

class ContractError(Exception):
    def __init__(self, message: str, status_code: int = 400): self.message, self.status_code = message, status_code

def _json_hash(x: dict) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _now(): return datetime.now(timezone.utc)
def _code(db):
    for _ in range(8):
        c = gen_contract_code(settings.tds_default_subject_code, settings.tds_default_region_industry)
        if not db.get(DigitalContract, c): return c
    raise ContractError("合约码分配失败", 500)

def _conn(db, cid):
    c = db.get(Connector, cid)
    if not c: raise ContractError("连接器不存在", 404)
    return c

def _outsourcing_extension(value):
    if value is None:return {}
    if set(value)!={'computationOutsourcing'}:raise ContractError('本入口仅支持 computationOutsourcing 合约扩展',422)
    ext=value['computationOutsourcing']
    if not isinstance(ext,dict) or not isinstance(ext.get('allowed'),bool) or not set(ext)<={'allowed','allowedConnectors'}:
        raise ContractError('外包扩展须包含 allowed 布尔许可和可选 allowedConnectors',422)
    ids=ext.get('allowedConnectors',[])
    if not isinstance(ids,list) or not all(isinstance(x,str) and x.strip() for x in ids) or len(set(ids))!=len(ids):raise ContractError('外包计算连接器许可须为唯一标识列表',422)
    return copy.deepcopy(value)

def _document(product, provider, consumer, contract_id, username, body, status="initiated"):
    now = _now()
    mode = product.transaction_mode
    # The contract document is the standard TC609 representation. Product
    # policy input is compiled into standard constraint entries, never stored
    # as a second platform-specific policy format.
    constraints = [{"constraintName": "executionEnv", "constraintOperator": "isA", "constraintValue": body.execution_env}]
    if body.application_code:
        constraints.append({"constraintName": "application", "constraintOperator": "isA", "constraintValue": [body.application_code]})
    policies = body.policies if body.policies is not None else (product.baseline_policies or [])
    for p in policies:
        raw = p.model_dump(by_alias=True) if hasattr(p, "model_dump") else p
        policy_constraints = raw.get("constraints") if isinstance(raw, dict) else None
        if isinstance(policy_constraints, dict):
            for name, value in policy_constraints.items():
                if name in {"exec_env", "executionEnv", "application"}:
                    continue
                if name == "time_window" and isinstance(value, dict):
                    if value.get("from"):
                        constraints.append({"constraintName": "time", "constraintOperator": "gteq", "constraintValue": value["from"]})
                    if value.get("to"):
                        constraints.append({"constraintName": "time", "constraintOperator": "lt", "constraintValue": value["to"]})
                elif value is not None:
                    constraints.append({"constraintName": name, "constraintOperator": "lteq" if name in {"count", "frequency", "data_record"} else "isA", "constraintValue": value})

    def ent(conn, role):
        return {
            "signatoryEntityId": conn.tds_code or conn.id,
            "signatoryEntityName": conn.org_name or conn.name,
            "signatoryType": role,
            "signature": None,
        }

    expansion = {
        "contractVersion": "1.0",
        "businessType": "DATA_PRODUCT_USAGE",
        "platformSignature": None,
    }
    if body.purpose:
        expansion["purpose"] = body.purpose
    extension=_outsourcing_extension(body.contract_expansion)
    if extension and mode!='negotiate':raise ContractError('外包计算许可需要双方协商签署，不能在直接接受时自行扩权',403)
    expansion.update(extension)
    policy_expansion = {
        "resultType": {
            "type": "application_output",
            "description": "按合约获准应用的公开输出接口交付结果；具体结果限制由协商策略声明",
            "allowedValues": ["application_output", "intersection_cardinality", "intersection_set", "secret_shares"],
        },
        "cryptoProtocolParams": {
            "paramsHash": None,
            "paramsDescription": "密码协议参数配置文件哈希，由隐私保护计算系统在作业创建时报告",
        },
        "applicationImages": {"allowedImages": []},
        "readyTimeout": "PT5M",
    }
    if body.policy_expansion:
        policy_expansion.update(body.policy_expansion)
    doc = {
        "$schema": "TC609-6-2025-14",
        "contractInfo": {
            "contractId": contract_id,
            "contractName": product.name,
            "contractAbstract": product.description,
            "contractStatus": status,
            "createTime": now.isoformat(),
            "signMode": mode,
            "signatoryEntities": [ent(provider, "provider"), ent(consumer, "consumer")],
            "signatureList": [],
            "signTime": None,
            "indate": {"activationTime": now.isoformat(), "endTime": now.replace(year=now.year + 1).isoformat()},
            "expansionItem": expansion,
        },
        "contractPolicies": [{
            "$comment": "获准应用计算与结果交付",
            "policyType": "permission",
            "subjectInfo": {
                "dataProductId": product.id,
                "dataProductName": product.name,
                "dataProductEntityId": provider.tds_code or provider.id,
            },
            "executionNodeInfo": {
                "providerNodeId": provider.tds_code or provider.id,
                "providerNodeName": provider.org_name or provider.name,
                "consumerNodeId": consumer.tds_code or consumer.id,
                "consumerNodeName": consumer.org_name or consumer.name,
            },
            "actions": ["process", "compute", "delivery"],
            "constraints": constraints,
            "policyExpansion": policy_expansion,
        }],
    }
    return validate_document(doc)

def _save_version(db, c, doc, op, user):
    doc = validate_document(doc)
    prev = c.document_hash if c.document_hash else None
    h = _json_hash(doc); v = c.current_version or 0
    c.document, c.document_hash, c.current_version = doc, h, v
    row = DigitalContractVersion(contract_id=c.contract_id, version=v, operation=op, document=doc, document_hash=h, previous_hash=prev, created_by=user)
    c.versions.append(row); return row

def _owned(db, identity, username):
    return identity == username or bool(db.scalar(select(Connector).where(((Connector.tds_code == identity) | (Connector.id == identity)), Connector.created_by == username)))

def _signature_material(document, entity_id):
    material = copy.deepcopy(document)
    material["contractInfo"]["signatureList"] = []
    material["contractInfo"]["signTime"] = None
    material["contractInfo"]["contractStatus"] = "negotiating"
    return {"document": material, "signatoryEntityId": entity_id}

def _make_signature(db, document, entity_id, subject):
    payload = _signature_material(document, entity_id)
    signed = sign_payload(db, subject, payload)
    key = db.scalar(select(UserSigningKey).where(UserSigningKey.key_id == signed["key_id"]))
    if not key or not verify_payload(key, payload, signed["signature"]):
        raise ContractError("合约签名验签失败", 400)
    return {"signatoryEntityId": entity_id, "signatureAlgorithm": signed["algorithm"], "signingKeyId": signed["key_id"], "signatureValue": signed["signature"], "signatureHash": _json_hash({"s":signed["signature"]}), "signatoryTime": _now().isoformat()}

def request(db: Session, product_id: str, username: str, is_admin: bool, body: ContractRequest):
    if is_admin: raise ContractError("管理员不可申请使用数据产品", 403)
    product = db.get(DataProduct, product_id)
    if not product or product.status != "listed": raise ContractError("产品不存在或未上架", 404)
    consumer = _conn(db, body.consumer_connector_id); provider = _conn(db, product.provider_connector_id)
    if consumer.created_by != username: raise ContractError("只能使用自己的连接器申请", 403)
    # `active` is the post-certificate-activation state of an approved
    # connector. Both states are eligible to participate in a contract.
    if consumer.status not in {"approved", "active"}: raise ContractError("用数方连接器未审批通过", 409)
    status = "negotiating" if product.transaction_mode == "negotiate" else "signed"
    c = DigitalContract(contract_id=_code(db), document={}, document_hash="", current_version=1, created_by=username)
    doc = _document(product, provider, consumer, c.contract_id, username, body, status)
    if status == "signed":
        # accept 模式仍需双方签名，沿用用户签名服务写入标准 signatureList。
        sigs=[]
        for entity, subject in (
            (doc["contractInfo"]["signatoryEntities"][0], provider.created_by),
            (doc["contractInfo"]["signatoryEntities"][1], username),
        ):
            sigs.append(_make_signature(db, doc, entity["signatoryEntityId"], subject))
        doc["contractInfo"]["signatureList"] = sigs; doc["contractInfo"]["signTime"] = _now().isoformat(); doc["contractInfo"]["contractStatus"] = "filed"
    db.add(c); _save_version(db,c,doc,"create",username)
    audit_append(db,event_type="contract.created",stream_id=contract_stream(c.contract_id),resource_type="digital_contract",resource_id=c.contract_id,actor={"subject":username},payload={"document_hash":c.document_hash})
    db.commit(); db.refresh(c); return c

def _get(db, cid):
    c=db.get(DigitalContract,cid)
    if not c: raise ContractError("合约不存在",404)
    return c
def get(db,cid,username,is_operator):
    c=_get(db,cid)
    entity_ids={x["signatoryEntityId"] for x in c.document["contractInfo"]["signatoryEntities"]}
    participant_owned=any(_owned(db,entity_id,username) for entity_id in entity_ids)
    if not is_operator and c.created_by!=username and not participant_owned: raise ContractError("无权访问",403)
    return c

def _owned_entity_ids(db: Session, username: str) -> set[str]:
    identities = {username}
    for connector in db.scalars(select(Connector).where(Connector.created_by == username)):
        identities.add(connector.id)
        if connector.tds_code:
            identities.add(connector.tds_code)
    return identities

def _contract_entity_ids(contract: DigitalContract) -> set[str]:
    info = contract.document.get("contractInfo") if isinstance(contract.document, dict) else None
    entities = info.get("signatoryEntities") if isinstance(info, dict) else None
    return {
        str(entity.get("signatoryEntityId"))
        for entity in (entities or [])
        if isinstance(entity, dict) and entity.get("signatoryEntityId")
    }

def list_contracts(db,username,is_operator):
    contracts = list(db.scalars(select(DigitalContract).order_by(DigitalContract.created_at.desc())))
    if is_operator:
        return contracts
    identities = _owned_entity_ids(db, username)
    return [contract for contract in contracts
            if contract.created_by == username or _contract_entity_ids(contract) & identities]
def propose(db,cid,username,is_operator,body:ProposeRequest):
    c=get(db,cid,username,is_operator); doc=copy.deepcopy(c.document)
    extension=_outsourcing_extension(body.contract_expansion)
    doc['contractInfo'].setdefault('expansionItem',{}).update(extension)
    doc["contractPolicies"]=body.contract_policies; doc["contractInfo"]["contractStatus"]="negotiating"; doc["contractInfo"]["signatureList"]=[]; doc["contractInfo"]["signTime"]=None; c.current_version+=1; _save_version(db,c,doc,"propose",username); db.commit(); db.refresh(c); return c
def sign(db,cid,username,is_operator):
    c=get(db,cid,username,is_operator); doc=dict(c.document); info=doc["contractInfo"]; entities=info["signatoryEntities"]; target=next((e for e in entities if _owned(db,e["signatoryEntityId"],username)),None)
    if not target: raise ContractError("仅合约参与方可签署",403)
    if any(s["signatoryEntityId"]==target["signatoryEntityId"] for s in info["signatureList"]): raise ContractError("该主体已签署",409)
    info["signatureList"].append(_make_signature(db,doc,target["signatoryEntityId"],username));
    if len(info["signatureList"])==len(entities): info["contractStatus"]="filed"; info["signTime"]=_now().isoformat()
    c.current_version+=1; _save_version(db,c,doc,"sign",username); db.commit(); db.refresh(c); return c
def file(db,cid,username,is_operator):
    c=get(db,cid,username,is_operator); doc=dict(c.document); doc["contractInfo"]["contractStatus"]="filed"; c.current_version+=1; _save_version(db,c,doc,"file",username); db.commit(); db.refresh(c); return c
def terminate(db,cid,username,is_operator):
    c=get(db,cid,username,is_operator); doc=dict(c.document); doc["contractInfo"]["contractStatus"]="terminated"; c.current_version+=1; _save_version(db,c,doc,"terminate",username); db.commit(); db.refresh(c); return c
def reject(db,cid,username,is_operator):
    c=get(db,cid,username,is_operator); doc=dict(c.document); doc["contractInfo"]["contractStatus"]="rejected"; c.current_version+=1; _save_version(db,c,doc,"reject",username); db.commit(); db.refresh(c); return c
