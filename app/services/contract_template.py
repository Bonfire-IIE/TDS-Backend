"""合约模板业务逻辑：系统预置（懒加载种子）+ 用户自建 / 编辑 / 删除。"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.contract_template import ContractTemplate
from app.schemas.contract_template import TemplateCreate, TemplateUpdate


class TemplateError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# 预置系统模板种子（策略结构见 schemas.product.Policy；操作词表与 exec_env 取值须一致）
_SYSTEM_SEED: list[dict] = [
    {
        "name": "公益开放-仅MPC计算",
        "description": "面向公益开放场景：仅允许访问与读取，且限定在 MPC 安全多方计算环境执行。",
        "policies": [
            {
                "type": "allow",
                "actions": ["access", "read"],
                "constraints": {"time_window": None, "count": None, "exec_env": "mpc"},
            },
        ],
    },
    {
        "name": "标准协商-联合统计",
        "description": "常见协商场景：允许访问/读取/加工，沙箱内执行且限次数上限 100。",
        "policies": [
            {
                "type": "allow",
                "actions": ["access", "read", "process"],
                "constraints": {"time_window": None, "count": 100, "exec_env": "sandbox"},
            },
        ],
    },
    {
        "name": "严格-仅沙箱计算禁下载导出",
        "description": "高安全场景：仅允许沙箱内访问/读取/加工，明确禁止下载与导出。",
        "policies": [
            {
                "type": "allow",
                "actions": ["access", "read", "process"],
                "constraints": {"time_window": None, "count": None, "exec_env": "sandbox"},
            },
            {
                "type": "prohibit",
                "actions": ["download", "export"],
                "constraints": {"time_window": None, "count": None, "exec_env": None},
            },
        ],
    },
]


def seed_system_templates(db: Session) -> None:
    """懒加载：首次访问时若无 system 模板则插入预置模板。"""
    exists = db.execute(
        select(ContractTemplate).where(ContractTemplate.scope == "system").limit(1)
    ).first()
    if exists:
        return
    for item in _SYSTEM_SEED:
        db.add(
            ContractTemplate(
                name=item["name"],
                description=item["description"],
                policies=item["policies"],
                scope="system",
                owner=None,
            )
        )
    db.commit()


def list_templates(db: Session, username: str) -> list[ContractTemplate]:
    """系统模板 + 当前用户自己的模板。"""
    seed_system_templates(db)
    stmt = (
        select(ContractTemplate)
        .where(
            or_(
                ContractTemplate.scope == "system",
                (ContractTemplate.scope == "user") & (ContractTemplate.owner == username),
            )
        )
        .order_by(ContractTemplate.scope.desc(), ContractTemplate.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def get(db: Session, template_id: str, username: str, is_operator: bool) -> ContractTemplate:
    row = db.get(ContractTemplate, template_id)
    if not row:
        raise TemplateError("合约模板不存在", 404)
    # 可见性：system 对所有人可见；user 模板仅属主/operator 可见
    if row.scope == "user" and not is_operator and row.owner != username:
        raise TemplateError("无权访问该模板", 403)
    return row


def create(db: Session, username: str, is_operator: bool, body: TemplateCreate) -> ContractTemplate:
    # scope 裁决：operator 可显式建 system 模板；其余一律 user
    scope = "user"
    owner: str | None = username
    if body.scope == "system":
        if not is_operator:
            raise TemplateError("仅运营方可创建系统模板", 403)
        scope = "system"
        owner = None

    row = ContractTemplate(
        name=body.name,
        description=body.description,
        policies=[p.model_dump(by_alias=True) for p in body.policies],
        scope=scope,
        owner=owner,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _require_editable(row: ContractTemplate, username: str, is_operator: bool) -> None:
    if row.scope == "system":
        if not is_operator:
            raise TemplateError("系统模板仅运营方可修改", 403)
        return
    # user 模板：属主或 operator
    if not is_operator and row.owner != username:
        raise TemplateError("无权修改该模板", 403)


def update(
    db: Session, template_id: str, username: str, is_operator: bool, body: TemplateUpdate
) -> ContractTemplate:
    row = db.get(ContractTemplate, template_id)
    if not row:
        raise TemplateError("合约模板不存在", 404)
    _require_editable(row, username, is_operator)
    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.policies is not None:
        row.policies = [p.model_dump(by_alias=True) for p in body.policies]
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, template_id: str, username: str, is_operator: bool) -> None:
    row = db.get(ContractTemplate, template_id)
    if not row:
        raise TemplateError("合约模板不存在", 404)
    _require_editable(row, username, is_operator)
    db.delete(row)
    db.commit()
