"""隐私计算作业业务逻辑：发起（建路由+建授权+组装配置+提交 KusciaJob）/ 状态同步 / 检索。

闭环最后一环：合约(filed) + 应用(AppImage) + 两方输入 DomainData
→ 确保双向路由与授权 → 组装 task_input_config（PSI）→ 提交 KusciaJob。
中心化模式无作业审批，提交后直接置 running，由 sync_status 轮询回填结果。

task_input_config 以 design/psi-job-reference.json 为模板（已实测跑通两方 PSI），
仅替换 domain / 输入输出 id / 求交列，其余（spu/heu 设备、协议参数）保持一致。
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.identifier import gen_data_code
from app.integrations.kuscia import KusciaError, get_kuscia_client
from app.models.appimage import AppImage
from app.models.connector import Connector
from app.models.contract import DigitalContract
from app.models.job import Job
from app.models.product import DataProduct
from app.schemas.job import JobCreate
from app.services import usage as usage_service
from app.services.audit import append as audit_append

# --- PSI 引擎固定参数（复用 design/psi-job-reference.json 中实测配置）---
_SPU_CONFIG = json.dumps({
    "runtime_config": {"protocol": "SEMI2K", "field": "FM128"},
    "link_desc": {
        "connect_retry_times": 60,
        "connect_retry_interval_ms": 1000,
        "brpc_channel_protocol": "http",
        "brpc_channel_connection_type": "pooled",
        "recv_timeout_ms": 1200000,
        "http_timeout_ms": 1200000,
    },
})
_HEU_CONFIG = json.dumps({"mode": "PHEU", "schema": "paillier", "key_size": 2048})


class JobError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------- 权限/归属 ----------
def _owns(db: Session, connector_id: str, username: str) -> bool:
    conn = db.get(Connector, connector_id)
    return bool(conn and conn.created_by == username)


# ---------- 作业码 ----------
def _new_job_code() -> str:
    """生成作业展示码（复用数据码生成器，扩展码标记 JOB）。"""
    return gen_data_code(
        "product", settings.tds_default_subject_code,
        settings.tds_default_region_industry, extension="JOB" + uuid.uuid4().hex[:8].upper(),
    )


# ---------- task_input_config 组装（PSI 两方求交）----------
def _build_task_input_config(
    provider_domain: str, consumer_domain: str,
    provider_dd: str, consumer_dd: str,
    join_keys: list[str], out_id: str, out_uri: str,
) -> str:
    """按 PSI 模板组装 task_input_config（返回 JSON 字符串）。

    sf_input_ids = [供方DomainData, 用方DomainData]；求交列 join_keys 同时作为
    两方主键；receiver_parties = 双方（结果各方本地可得）。
    """
    keys_attr = {"is_na": False, "ss": join_keys}
    cfg = {
        "sf_datasource_config": {
            provider_domain: {"id": "default-data-source"},
            consumer_domain: {"id": "default-data-source"},
        },
        "sf_cluster_desc": {
            "parties": [provider_domain, consumer_domain],
            "devices": [
                {
                    "name": "spu", "type": "spu",
                    "parties": [provider_domain, consumer_domain],
                    "config": _SPU_CONFIG,
                },
                {
                    "name": "heu", "type": "heu",
                    "parties": [provider_domain, consumer_domain],
                    "config": _HEU_CONFIG,
                },
            ],
            "ray_fed_config": {"cross_silo_comm_backend": "brpc_link"},
        },
        "sf_node_eval_param": {
            "domain": "data_prep",
            "name": "psi",
            "version": "1.0.0",
            "attr_paths": [
                "input/input_ds1/keys", "input/input_ds2/keys", "protocol",
                "sort_result", "receiver_parties", "allow_empty_result",
                "join_type", "input_ds1_keys_duplicated", "input_ds2_keys_duplicated",
            ],
            "attrs": [
                keys_attr,
                keys_attr,
                {"is_na": False, "s": "PROTOCOL_RR22"},
                {"b": True, "is_na": False},
                {"is_na": False, "ss": [provider_domain, consumer_domain]},
                {"is_na": True},
                {"is_na": False, "s": "inner_join"},
                {"b": True, "is_na": False},
                {"b": True, "is_na": False},
            ],
        },
        "sf_input_ids": [provider_dd, consumer_dd],
        "sf_output_ids": [out_id, out_id],
        "sf_output_uris": [out_uri, out_uri],
    }
    return json.dumps(cfg, ensure_ascii=False)


# ---------- 状态映射 ----------
def _map_state(kuscia_state: str | None) -> str:
    """Kuscia 作业相位 → TDS 作业状态。"""
    if kuscia_state == "Succeeded":
        return "succeeded"
    if kuscia_state in ("Failed", "Cancelled", "ApprovalReject"):
        return "failed"
    # Initialized / AwaitingApproval / Pending / Running
    return "running"


# ---------- 发起作业 ----------
def create_job(db: Session, username: str, is_operator: bool, body: JobCreate) -> Job:
    # ① 合约：必须已备案(filed)
    c = db.get(DigitalContract, body.contract_id)
    if not c:
        raise JobError("合约不存在", 404)
    if c.status != "filed":
        raise JobError(f"合约未备案（当前状态 {c.status}），无法发起作业", 409)

    # 调用者须为用数方（consumer 连接器属主）或运营方
    if not is_operator and not _owns(db, c.consumer_connector_id, username):
        raise JobError("仅用数方或运营方可发起作业", 403)

    # ② 应用能力：须在平台已登记且可用；若产品声明了 allowed_appimages 则须命中
    app = db.execute(
        select(AppImage).where(AppImage.name == body.app_image)
    ).scalar_one_or_none()
    if not app:
        raise JobError(f"应用能力 {body.app_image} 未在平台登记", 404)
    if app.status != "registered":
        raise JobError(f"应用能力 {body.app_image} 已下架", 409)

    product = db.get(DataProduct, c.product_id)
    if product and product.allowed_appimages and body.app_image not in product.allowed_appimages:
        raise JobError(f"应用 {body.app_image} 不在产品允许的能力列表内", 400)

    # ③ 供/用连接器与各自 Kuscia domain
    provider = db.get(Connector, c.provider_connector_id)
    consumer = db.get(Connector, c.consumer_connector_id)
    if not provider or not consumer:
        raise JobError("合约相关连接器不存在", 404)
    provider_domain = provider.kuscia_domain_id
    consumer_domain = consumer.kuscia_domain_id

    # 使用控制必须发生在建路由、授权和提交作业等数据面副作用之前。
    try:
        usage_record = usage_service.authorize_and_reserve(
            db, c, username, consumer.id, action="process",
            exec_env=app.capability, app_image=body.app_image,
        )
    except usage_service.UsageError as e:
        raise JobError(e.message, e.status_code) from e

    kc = get_kuscia_client()
    prefix = settings.kuscia_lite_ctr_prefix

    # ④ 确保双向 ClusterDomainRoute（幂等）
    try:
        kc.create_cluster_route(provider_domain, consumer_domain, dst_host=prefix + consumer_domain)
        kc.create_cluster_route(consumer_domain, provider_domain, dst_host=prefix + provider_domain)
    except KusciaError as e:
        usage_service.release(db, usage_record.id, f"建立连接器路由失败: {e}")
        raise JobError(f"建立连接器路由失败: {e}", 502) from e

    # ⑤ SecretFlow PSI 需要双向 DomainDataGrant；自包含/自管输入应用可显式关闭。
    template = app.job_template or {}
    if template.get("requires_domaindata", True):
        try:
            kc.create_domaindatagrant(provider_domain, body.input_provider_domaindata_id, consumer_domain)
            kc.create_domaindatagrant(consumer_domain, body.input_consumer_domaindata_id, provider_domain)
        except KusciaError as e:
            usage_service.release(db, usage_record.id, f"建立数据授权失败: {e}")
            raise JobError(f"建立数据授权失败: {e}", 502) from e

    # ⑥ 组装 task。自定义 AppImage 可声明角色和输入配置；否则走 SecretFlow PSI。
    out_id = "job-out-" + uuid.uuid4().hex[:12]
    out_uri = out_id + ".csv"
    if template:
        roles = template.get("party_roles", {})
        parties = [
            {"domain_id": provider_domain, "role": roles.get("provider", "")},
            {"domain_id": consumer_domain, "role": roles.get("consumer", "")},
        ]
        task_input_config = template.get("task_input_config", "")
        task_alias = template.get("alias", "custom-task")
        out_uri = template.get("result_uri", out_uri)
    else:
        parties = [{"domain_id": provider_domain}, {"domain_id": consumer_domain}]
        task_input_config = _build_task_input_config(
            provider_domain, consumer_domain,
            body.input_provider_domaindata_id, body.input_consumer_domaindata_id,
            body.join_keys or ["id"], out_id, out_uri,
        )
        task_alias = "single-psi"

    # ⑦ 提交 KusciaJob（initiator=供方 domain，与实测配置一致；parties 顺序=[供,用]）
    kuscia_job_id = "tds-job-" + uuid.uuid4().hex[:12]
    job_dict = {
        "job_id": kuscia_job_id,
        "initiator": provider_domain,
        "max_parallelism": 2,
        "tasks": [{
            "task_id": kuscia_job_id + "-task",
            "alias": task_alias,
            "app_image": body.app_image,
            "parties": parties,
            "priority": 100,
            "task_input_config": task_input_config,
        }],
    }
    try:
        kc.create_job(job_dict)
    except KusciaError as e:
        usage_service.release(db, usage_record.id, f"提交 Kuscia 作业失败: {e}")
        raise JobError(f"提交 Kuscia 作业失败: {e}", 502) from e

    # ⑧ 落库（中心化无审批，直接 running）
    job = Job(
        job_code=_new_job_code(),
        name=body.name or f"{c.name}-PSI",
        contract_id=c.contract_id,
        usage_record_id=usage_record.id,
        product_id=c.product_id,
        app_image=body.app_image,
        initiator_connector_id=provider.id,
        initiator_domain=provider_domain,
        provider_connector_id=provider.id,
        provider_domain=provider_domain,
        consumer_connector_id=consumer.id,
        consumer_domain=consumer_domain,
        input_provider_domaindata_id=body.input_provider_domaindata_id,
        input_consumer_domaindata_id=body.input_consumer_domaindata_id,
        kuscia_job_id=kuscia_job_id,
        status="running",
        result_domaindata_id=out_id,
        result_uri=out_uri,
        created_by=username,
    )
    db.add(job)
    db.flush()
    job_id = job.id
    audit_append(db, event_type="job.submitted", stream_id=f"job:{job.id}", resource_type="job", resource_id=job.id, actor={"subject": username}, payload={"contract_id": c.contract_id, "app_image": body.app_image, "kuscia_job_id": kuscia_job_id, "usage_record_id": usage_record.request_id})
    usage_service.consume(db, usage_record.id, job_id)
    db.refresh(job)
    return job


# ---------- 状态同步 ----------
def sync_status(db: Session, job: Job) -> Job:
    """查询 Kuscia 作业状态并回填本地（已终态则跳过）。"""
    if job.status in ("succeeded", "failed") or not job.kuscia_job_id:
        return job
    try:
        data = get_kuscia_client().query_job(job.kuscia_job_id)
    except KusciaError as e:
        # 查询失败不改状态，仅记录错误（保持 running，稍后可重试）
        job.error = f"状态查询失败: {e}"
        db.commit()
        db.refresh(job)
        return job

    status_obj = data.get("status", {}) or {}
    new_status = _map_state(status_obj.get("state"))
    job.status = new_status
    if new_status == "failed":
        message = status_obj.get("err_msg") or status_obj.get("message") or "作业执行失败"
        state = status_obj.get("state") or "Failed"
        # Kuscia master status is the authoritative summary; connector application logs stay local.
        job.error = message
        job.failure_info = {
            "stage": "scheduling" if state in ("ApprovalReject", "Cancelled") else "kuscia_task",
            "source": "kuscia_master",
            "domain_id": status_obj.get("domain_id") or status_obj.get("domainId"),
            "code": status_obj.get("code") or state.upper(),
            "message": message,
            "retryable": state not in ("ApprovalReject", "Cancelled"),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "detail_scope": "仅为 Kuscia 控制面摘要；应用详细日志需由对应连接器管理员查看",
        }
    elif new_status == "succeeded":
        job.error = None
        job.failure_info = None
        audit_append(db, event_type="job.completed", stream_id=f"job:{job.id}", resource_type="job", resource_id=job.id, payload={"kuscia_job_id": job.kuscia_job_id, "status": new_status})
    if new_status == "failed":
        audit_append(db, event_type="job.failed", stream_id=f"job:{job.id}", resource_type="job", resource_id=job.id, payload={"kuscia_job_id": job.kuscia_job_id, "error": job.error})
        # 结果 DomainData/URI 在发起时已按输出配置确定
    db.commit()
    db.refresh(job)
    return job


# ---------- 检索 ----------
def _visible(db: Session, username: str, is_operator: bool):
    stmt = select(Job).order_by(Job.created_at.desc())
    if is_operator:
        return stmt
    owned = db.execute(
        select(Connector.id).where(Connector.created_by == username)
    ).scalars().all()
    conds = [Job.created_by == username]
    if owned:
        conds.append(Job.provider_connector_id.in_(owned))
        conds.append(Job.consumer_connector_id.in_(owned))
    return stmt.where(or_(*conds))


def list_jobs(db: Session, username: str, is_operator: bool) -> list[Job]:
    return list(db.execute(_visible(db, username, is_operator)).scalars())


def get(db: Session, job_id: str, username: str, is_operator: bool, *, refresh: bool = False) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise JobError("作业不存在", 404)
    if not is_operator:
        related = (
            job.created_by == username
            or _owns(db, job.provider_connector_id, username)
            or _owns(db, job.consumer_connector_id, username)
        )
        if not related:
            raise JobError("无权访问该作业", 403)
    if refresh:
        job = sync_status(db, job)
    return job
