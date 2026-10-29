"""TC609 数字合约领域模型和规范化工具。

平台持久化和签名的对象就是该文档；这里不定义 KusciaJob 等调度器概念。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


OPERATORS = {"eq", "gt", "gteq", "hasPart", "isA", "isAllOf", "isAnyOf", "isNoneOf", "isPartOf", "lt", "lteq", "neq"}


class StandardModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, alias_generator=lambda s: ''.join([s.split('_')[0]] + [x[:1].upper()+x[1:] for x in s.split('_')[1:]]))


class SignatoryEntity(StandardModel):
    signatory_entity_id: str
    signatory_entity_name: str
    signatory_type: Literal["provider", "consumer", "operator", "other"]


class SignatureEntry(StandardModel):
    signatory_entity_id: str
    signature_algorithm: str
    signing_key_id: str
    signature_value: str
    signature_hash: str
    signatory_time: datetime


class Indate(StandardModel):
    activation_time: datetime
    end_time: datetime


class ContractInfo(StandardModel):
    contract_id: str
    contract_name: str
    contract_abstract: str | None = None
    contract_status: Literal["initiated", "negotiating", "signed", "filed", "executing", "terminated", "rejected"]
    create_time: datetime
    sign_mode: Literal["accept", "negotiate"]
    signatory_entities: list[SignatoryEntity] = Field(min_length=1)
    signature_list: list[SignatureEntry] = Field(default_factory=list)
    sign_time: datetime | None = None
    indate: Indate
    expansion_item: dict[str, Any] = Field(default_factory=dict)


class SubjectInfo(StandardModel):
    data_product_id: str
    data_product_name: str
    data_product_entity_id: str


class ExecutionNodeInfo(StandardModel):
    provider_node_id: str
    provider_node_name: str
    consumer_node_id: str
    consumer_node_name: str


class Constraint(StandardModel):
    constraint_name: str
    constraint_operator: str
    constraint_value: Any

    @model_validator(mode="after")
    def check_operator(self):
        if self.constraint_operator not in OPERATORS:
            raise ValueError(f"非法 constraint_operator: {self.constraint_operator}")
        return self


class ContractPolicy(StandardModel):
    policy_type: Literal["permission", "prohibition", "obligation"]
    subject_info: SubjectInfo
    execution_node_info: ExecutionNodeInfo
    actions: list[str]
    constraints: list[Constraint] = Field(default_factory=list)
    policy_expansion: dict[str, Any] = Field(default_factory=dict)


class DigitalContractDocument(StandardModel):
    schema_: Literal["TC609-6-2025-14"] = Field(alias="$schema", serialization_alias="$schema")
    contract_info: ContractInfo
    contract_policies: list[ContractPolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def lifecycle_rules(self):
        info = self.contract_info
        if info.indate.end_time <= info.indate.activation_time:
            raise ValueError("indate.end_time 必须晚于 activation_time")
        entity_ids = {x.signatory_entity_id for x in info.signatory_entities}
        signature_ids = {x.signatory_entity_id for x in info.signature_list}
        if not signature_ids <= entity_ids:
            raise ValueError("signature_list 包含未声明的签署主体")
        if info.contract_status in {"filed", "executing"} and signature_ids != entity_ids:
            raise ValueError("备案或执行中的合约必须包含全部主体签名")
        return self


def validate_document(document: dict, *, require_signatures: bool = False) -> dict:
    parsed = DigitalContractDocument.model_validate(document)
    if require_signatures:
        entities = parsed.contract_info.signatory_entities
        signatures = parsed.contract_info.signature_list
        if {x.signatory_entity_id for x in entities} != {x.signatory_entity_id for x in signatures}:
            raise ValueError("签署完成的合约必须包含全部主体签名")
    return parsed.model_dump(by_alias=True, mode="json")


def info(document: dict) -> dict:
    return document["contractInfo"]


def primary_policy(document: dict) -> dict:
    policies = document["contractPolicies"]
    if not policies:
        raise ValueError("合约没有可执行策略")
    return policies[0]


def execution_nodes(document: dict) -> dict:
    return primary_policy(document)["executionNodeInfo"]


def subject(document: dict) -> dict:
    return primary_policy(document)["subjectInfo"]


def allowed_app_images(document: dict) -> list[str]:
    policy_expansion = primary_policy(document).get("policyExpansion") or {}
    execution = policy_expansion.get("applicationExecution") or {}
    return execution.get("allowedAppImages") or []


def allowed_applications(document: dict) -> list[str]:
    """Project the standard application constraint into business app codes."""
    values: list[str] = []
    for policy in document.get("contractPolicies") or []:
        for constraint in policy.get("constraints") or []:
            if constraint.get("constraintName") != "application":
                continue
            value = constraint.get("constraintValue")
            values.extend(value if isinstance(value, list) else [value])
    return [str(value) for value in dict.fromkeys(values) if value]


def legacy_policy_input(document: dict) -> list[dict]:
    """OPA 输入适配：由标准策略确定性编译，不是第二份合约模型。"""
    result = []
    for p in document["contractPolicies"]:
        constraints: dict[str, Any] = {}
        time_window: dict[str, Any] = {}
        for item in p.get("constraints", []):
            name, operator, value = item.get("constraintName"), item.get("constraintOperator"), item.get("constraintValue")
            if name == "executionEnv" and operator in {"eq", "isA"}:
                constraints["exec_env"] = value
            elif name == "count" and operator in {"eq", "lteq"}:
                constraints["count"] = value
            elif name == "time" and operator == "gteq":
                time_window["from"] = value
            elif name == "time" and operator in {"lt", "lteq"}:
                time_window["to"] = value
            elif operator == "eq":
                constraints[name] = value
        if time_window:
            constraints["time_window"] = time_window
        result.append({"effect": "allow" if p["policyType"] == "permission" else "prohibit", "actions": {a: True for a in p.get("actions", [])}, "constraints": constraints, "obligations": []})
    return result
