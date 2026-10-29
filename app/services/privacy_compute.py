from __future__ import annotations
from app.core.config import settings

from sqlalchemy import select
from datetime import datetime, timezone
import uuid, hashlib, json
from sqlalchemy.orm import Session

from app.models.contract import DigitalContract
from app.models.capability import DataResourceBinding, PrivacyApplication, PrivacyApplicationBinding, ConnectorCapability
from app.models.connector import Connector
from app.services.standard_contract import execution_nodes
from app.models.privacy_compute import PrivacyComputeProject
from app.schemas.privacy_compute import PrivacyProjectCreate, PrivacyRunCreate
from app.services.standard_contract import primary_policy, info as contract_info


class PrivacyComputeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


def _constraint(document: dict, name: str):
    for item in primary_policy(document).get("constraints", []):
        if item.get("constraintName") == name:
            return item.get("constraintValue")
    return None


def _single_application_workflow(
    implementation_metadata: dict,
    provider_connector_id: str,
    consumer_connector_id: str,
    provider_resource_ref: str,
    consumer_resource_ref: str,
    parameters: dict,
) -> dict:
    """Compile a registered single AppImage contract into the generic DAG shape."""
    appimage = implementation_metadata.get("appimage") or {}
    app_name = str(appimage.get("name") or "")
    io_schema = appimage.get("io_schema") or implementation_metadata.get("io_schema") or {}
    job_template = appimage.get("job_template") or {}
    provider_role = str(implementation_metadata.get("provider_role") or job_template.get("provider_role") or "")
    consumer_role = str(implementation_metadata.get("consumer_role") or job_template.get("consumer_role") or "")
    if not app_name or not provider_role or not consumer_role:
        raise PrivacyComputeError("应用镜像缺少名称或参与方角色映射", 422)

    resources = {
        "provider": (provider_connector_id, provider_resource_ref),
        "consumer": (consumer_connector_id, consumer_resource_ref),
    }
    input_bindings = []
    for port in io_schema.get("inputs") or []:
        name, role = str(port.get("name") or ""), str(port.get("role") or "")
        if not name or role not in resources:
            raise PrivacyComputeError("应用镜像输入端口缺少名称或 provider/consumer 归属", 422)
        connector_id, resource_ref = resources[role]
        input_bindings.append({
            "port": name,
            "connector_id": connector_id,
            "domaindata_id": resource_ref,
        })

    output_bindings = []
    for port in io_schema.get("outputs") or []:
        name = str(port.get("name") or "")
        if not name:
            raise PrivacyComputeError("应用镜像输出端口缺少名称", 422)
        binding = {"port": name}
        formats = [str(value).lower() for value in port.get("formats") or [] if value]
        if len(formats) == 1:
            binding["format"] = formats[0]
        output_bindings.append(binding)

    node_id = "application-1"
    return {
        "schedule_mode": "Strict",
        "max_parallelism": 1,
        "nodes": [{
            "id": node_id,
            "alias": str(implementation_metadata.get("task_alias") or job_template.get("task_alias") or node_id),
            "app_image": app_name,
            "parties": [
                {"connector_id": provider_connector_id, "role": provider_role},
                {"connector_id": consumer_connector_id, "role": consumer_role},
            ],
            "input_bindings": input_bindings,
            "output_bindings": output_bindings,
            "parameters": parameters or {},
        }],
        "edges": [],
    }


def create_project(db: Session, username: str, body: PrivacyProjectCreate) -> PrivacyComputeProject:
    contract = db.get(DigitalContract, body.contract_id)
    if not contract:
        raise PrivacyComputeError("数字合约不存在", 404)
    status = contract_info(contract.document).get("contractStatus")
    if status not in {"filed", "signed"}:
        raise PrivacyComputeError("只能基于已签署并备案的数字合约创建隐私计算项目", 409)
    application = db.get(PrivacyApplication, body.application_code)
    if not application or application.status != "published":
        raise PrivacyComputeError("隐私计算应用不存在或未发布", 404)
    allowed = _constraint(contract.document, "application")
    if allowed and body.application_code not in (allowed if isinstance(allowed, list) else [allowed]):
        raise PrivacyComputeError("应用不在数字合约允许范围内", 403)
    env = _constraint(contract.document, "executionEnv")
    if env and str(env) != application.execution_env_code:
        raise PrivacyComputeError("应用执行环境与数字合约不匹配", 403)
    binding = db.scalar(select(PrivacyApplicationBinding).where(
        PrivacyApplicationBinding.application_code == body.application_code,
        PrivacyApplicationBinding.status == "published",
    ))
    if not binding:
        raise PrivacyComputeError("该应用尚未绑定可用的数据利用系统", 409)
    if db.scalar(select(PrivacyComputeProject).where(PrivacyComputeProject.contract_id == contract.contract_id)):
        raise PrivacyComputeError("一个数字合约只能创建一个隐私计算项目", 409)
    project = PrivacyComputeProject(
        name=body.name,
        description=body.description,
        contract_id=contract.contract_id,
        contract_version=contract.current_version,
        contract_document_hash=contract.document_hash,
        application_code=body.application_code,
        configuration=body.configuration or {},
        status="draft",
        created_by=username,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session, username: str, is_operator: bool) -> list[PrivacyComputeProject]:
    stmt = select(PrivacyComputeProject).order_by(PrivacyComputeProject.created_at.desc())
    if not is_operator:
        stmt = stmt.where(PrivacyComputeProject.created_by == username)
    return list(db.scalars(stmt))


def start_run(db: Session, username: str, is_operator: bool, project_id: str, body: PrivacyRunCreate):
    from app.models.privacy_compute import PrivacyComputeRun
    project = db.get(PrivacyComputeProject, project_id)
    if not project:
        raise PrivacyComputeError("隐私计算项目不存在", 404)
    if project.created_by != username and not is_operator:
        raise PrivacyComputeError("无权执行该隐私计算项目", 403)
    if body.idempotency_key:
        existing = db.scalar(select(PrivacyComputeRun).where(PrivacyComputeRun.project_id == project_id, PrivacyComputeRun.idempotency_key == body.idempotency_key))
        if existing:
            return existing
    # The center creates an abstract execution request. Downstream identifiers
    # and Kuscia calls belong to the connector execution gateway.
    # Input references must resolve to connector-side bindings.  The adapter
    # may translate the binding to a downstream identifier, but callers cannot
    # submit arbitrary external ids that bypass the platform catalog.
    app_binding = db.scalar(select(PrivacyApplicationBinding).where(
        PrivacyApplicationBinding.application_code == project.application_code,
        PrivacyApplicationBinding.status == "published",
    ))
    if not app_binding:
        raise PrivacyComputeError("该应用没有可用的执行实现", 409)
    application = db.get(PrivacyApplication, project.application_code)
    if not application:
        raise PrivacyComputeError("项目绑定的业务应用不存在", 409)
    from app.models.appimage import AppImage
    implementation_metadata = dict(app_binding.implementation_metadata or {})
    appimage_names = [app_binding.system_application_ref, project.application_code]
    configured_image = implementation_metadata.get("app_image")
    if isinstance(configured_image, str): appimage_names.append(configured_image)
    appimage = db.scalar(select(AppImage).where(AppImage.name.in_(appimage_names), AppImage.status == "registered"))
    # Bindings created before AppImage registration may only carry an image
    # coordinate in implementation_metadata. Resolve that coordinate without
    # introducing an engine-specific identifier into the platform request.
    if not appimage and configured_image:
        appimage = db.scalar(select(AppImage).where(
            AppImage.image_name == configured_image, AppImage.status == "registered"
        ))
    if not appimage and configured_image:
        appimage = db.scalar(select(AppImage).where(
            AppImage.name == configured_image, AppImage.status == "registered"
        ))
    if appimage:
        implementation_metadata.setdefault("task_input_template", appimage.task_input_template)
        implementation_metadata.setdefault("io_schema", appimage.io_schema or {})
        implementation_metadata.setdefault("party_schema", appimage.party_schema or {})
        # The platform sends the engine-neutral AppImage contract to the
        # connector.  Kuscia-specific material is interpreted only by the
        # connector adapter and is never persisted as a platform Kuscia object.
        implementation_metadata.setdefault("appimage", {
            "name": appimage.name,
            "display_name": appimage.display_name,
            "description": appimage.description,
            "capability": appimage.capability,
            "operations": appimage.operations or [],
            "uc_capabilities": appimage.uc_capabilities or [],
            "registry_source": appimage.registry_source,
            "registry": appimage.registry,
            "image_name": appimage.image_name,
            "image_tag": appimage.image_tag,
            "deploy_templates": appimage.deploy_templates or [],
            "config_templates": appimage.config_templates or {},
            "job_template": appimage.job_template or {},
            "io_schema": appimage.io_schema or {},
            "party_schema": appimage.party_schema or {},
            "parameter_schema": appimage.parameter_schema or {},
            "ui_schema": appimage.ui_schema or {},
            "task_input_template": appimage.task_input_template,
            "scope": appimage.scope,
            "status": appimage.status,
        })
    contract = db.get(DigitalContract, project.contract_id)
    if not contract:
        raise PrivacyComputeError("数字合约不存在", 404)
    nodes = execution_nodes(contract.document)
    provider = db.scalar(select(Connector).where((Connector.tds_code == nodes["providerNodeId"]) | (Connector.id == nodes["providerNodeId"])))
    consumer = db.scalar(select(Connector).where((Connector.tds_code == nodes["consumerNodeId"]) | (Connector.id == nodes["consumerNodeId"])))
    if not provider or not consumer:
        raise PrivacyComputeError("合约参与方连接器不存在", 409)

    def resource_binding(connector_id: str, resource_ref: str) -> DataResourceBinding:
        binding = db.scalar(select(DataResourceBinding).where(
            DataResourceBinding.connector_id == connector_id,
            DataResourceBinding.connector_resource_ref == resource_ref,
            DataResourceBinding.sync_status == "synced",
        ))
        if not binding:
            raise PrivacyComputeError(f"连接器输入资源尚未登记或同步: {resource_ref}", 409)
        return binding

    def resource_descriptor(binding: DataResourceBinding) -> dict:
        from app.models.catalog import DataCatalog
        resource = db.get(DataCatalog, binding.platform_resource_id)
        snapshot = dict(binding.metadata_snapshot or {})
        # DataCatalog is the current connector-facing projection.  The binding
        # snapshot may still contain the retired center datasource UUID after
        # the connector-local datasource migration.
        datasource_id = (resource.datasource_id if resource else None) or snapshot.get("datasource_ref")
        if resource:
            snapshot = {
                **snapshot,
                "name": resource.name,
                "data_type": resource.data_type,
                "columns": resource.columns or [],
                "datasource_ref": datasource_id,
                "connector_datasource_ref": datasource_id,
                "datasource_type": snapshot.get("datasource_type") or resource.datasource_type,
                "relative_uri": resource.relative_uri,
                "format": str(resource.resource_format or snapshot.get("format") or "").lower(),
            }
        return {
            "ref": binding.connector_resource_ref,
            "platform_resource_id": binding.platform_resource_id,
            "version": binding.version,
            "metadata": snapshot,
        }

    provider_binding = resource_binding(provider.id, body.input_provider_ref)
    consumer_binding = resource_binding(consumer.id, body.input_consumer_ref)

    requirements = app_binding.capability_requirements or []
    requirement_codes = [
        str(item.get("code")) if isinstance(item, dict) else str(item)
        for item in requirements
        if (isinstance(item, str) and item) or (isinstance(item, dict) and item.get("code"))
    ]

    def execution_target(connector: Connector) -> dict:
        capabilities = list(db.scalars(select(ConnectorCapability).where(
            ConnectorCapability.connector_id == connector.id,
            ConnectorCapability.status == "verified",
        )))
        by_code = {item.capability_code: item for item in capabilities}
        missing = [code for code in requirement_codes if code not in by_code]
        if missing:
            raise PrivacyComputeError(
                f"连接器 {connector.name} 尚未验证应用所需能力: {', '.join(missing)}", 409
            )
        candidates = [by_code[code] for code in requirement_codes] if requirement_codes else capabilities
        for capability in candidates:
            evidence = capability.evidence or {}
            network = evidence.get("network") or {}
            endpoint = network.get("execution_endpoint")
            if isinstance(endpoint, str) and endpoint:
                return {
                    "endpoint": endpoint,
                    "gateway_endpoint": network.get("gateway_endpoint"),
                    "connector_endpoint": network.get("connector_endpoint"),
                    "node_ref": network.get("execution_node_ref"),
                    "portal_browser_url": network.get("portal_browser_url"),
                    "storage_ref": network.get("execution_storage_ref"),
                    "capability_code": capability.capability_code,
                    "adapter_type": capability.adapter_type,
                }
        raise PrivacyComputeError(f"连接器 {connector.name} 没有可用的应用执行网关", 409)

    provider_target = execution_target(provider)
    consumer_target = execution_target(consumer)
    request_id = str(uuid.uuid4())
    workflow = _single_application_workflow(
        implementation_metadata,
        provider.id,
        consumer.id,
        body.input_provider_ref,
        body.input_consumer_ref,
        project.configuration or {},
    )
    request = {
        "scheduling_mode": settings.pets_scheduler_mode,
        "request_id": request_id,
        "project_id": project.id,
        "provider_connector_id": provider.id,
        "consumer_connector_id": consumer.id,
        "dispatch_connector_id": consumer.id,
        "provider_resource_ref": body.input_provider_ref,
        "consumer_resource_ref": body.input_consumer_ref,
        "provider_resource": resource_descriptor(provider_binding),
        "consumer_resource": resource_descriptor(consumer_binding),
        "application": {
            "code": project.application_code,
            "version": app_binding.system_application_version,
            "system_type": app_binding.system_type,
            "implementation_ref": app_binding.system_application_ref,
            "adapter_version": app_binding.adapter_version,
            "capability_requirements": requirements,
            "implementation_metadata": implementation_metadata,
            "input_schema": application.input_schema or {},
            "output_schema": application.output_schema or {},
            "task_input_template": implementation_metadata.get("task_input_template"),
        },
        "workflow": workflow,
        "configuration": project.configuration or {},
        "join_keys": body.join_keys,
        "contract_id": project.contract_id,
        "contract_version": project.contract_version,
        "contract_document_hash": project.contract_document_hash,
        # Generic connector execution endpoints are supplied by the center;
        # no Kuscia-specific identifiers are stored in the platform request.
        "provider_execution_endpoint": provider_target["endpoint"],
        "consumer_execution_endpoint": consumer_target["endpoint"],
        "provider_gateway_endpoint": provider_target["gateway_endpoint"],
        "consumer_gateway_endpoint": consumer_target["gateway_endpoint"],
        "provider_connector_endpoint": provider_target.get("connector_endpoint"),
        "consumer_connector_endpoint": consumer_target.get("connector_endpoint"),
        "provider_execution_node_ref": provider_target["node_ref"],
        "consumer_execution_node_ref": consumer_target["node_ref"],
        "provider_execution_storage_ref": provider_target["storage_ref"],
        "consumer_execution_storage_ref": consumer_target["storage_ref"],
        # Compatibility envelope consumed by the generic execution gateway.
        # The legacy endpoint keeps its public contract, while the payload now
        # has the same immutable workflow/snapshot shape as ProjectRun.
        "compiler_version": "privacy-compute-compat/v1",
        "workflow_hash": hashlib.sha256(json.dumps(workflow, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "result_guidance": {
            "kind": "application_output",
            "portal_directory": "/connectors",
            "portal_browser_urls": {connector.id:target["portal_browser_url"] for connector,target in ((provider,provider_target),(consumer,consumer_target)) if target.get("portal_browser_url")},
            "outputs": application.output_schema or {},
            "message": "执行完成后从连接器 Portal 的执行结果页面查看应用输出；平台仅保存结果摘要。",
        },
    }
    if not appimage:
        raise PrivacyComputeError("旧应用执行实现须关联已登记的 AppImage，才能进入统一执行与产物生命周期",409)
    # The legacy binding can use a business code distinct from its registered
    # component name. Resolve it once before entering the generic compiler.
    for node in request["workflow"]["nodes"]:
        node["app_image"]=appimage.name
    from app.services.execution_compat import materialize_execution_request
    from app.services.project import ProjectError
    try:
        request = materialize_execution_request(
            request, {appimage.name: appimage}, project_id=project.id, run_id=request_id,
        )
    except (ValueError, ProjectError) as exc:
        raise PrivacyComputeError(str(exc),422) from exc
    workflow=request["workflow"]
    request["workflow_hash"]=hashlib.sha256(json.dumps(workflow,sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()).hexdigest()
    submission = {
        "external_run_ref": None,
        "status": "pending-dispatch",
        "result": None,
        "error": None,
    }
    adapter_type = "privacy-compute"
    run = PrivacyComputeRun(
        id=request_id,
        project_id=project_id,
        status=submission.get("status", "pending"),
        system_type=adapter_type,
        external_run_ref=submission.get("external_run_ref"),
        result=submission.get("result"),
        error=submission.get("error"),
        evidence={"contract_version": project.contract_version, "contract_document_hash": project.contract_document_hash,
                  "execution_snapshot": {"compiler_version": request["compiler_version"], "workflow_hash": request["workflow_hash"], "workflow": workflow},
                  "execution_request": request},
        idempotency_key=body.idempotency_key,
        created_by=username,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def refresh_run(db: Session, username: str, is_operator: bool, project_id: str, run_id: str):
    from app.models.privacy_compute import PrivacyComputeRun

    project = db.get(PrivacyComputeProject, project_id)
    run = db.get(PrivacyComputeRun, run_id)
    if not project or not run or run.project_id != project_id:
        raise PrivacyComputeError("隐私计算运行记录不存在", 404)
    if project.created_by != username and not is_operator:
        raise PrivacyComputeError("无权查看该运行记录", 403)
    from app.core.config import settings
    if settings.pets_scheduler_mode == "master-lite":
        # The persistent center worker owns engine status; reading never fabricates failure.
        return run
    # Gateway-reported runs are already normalized by the connector. The
    # center never queries a downstream execution system directly.
    gateway_report = (run.evidence or {}).get("gateway_report")
    if run.external_run_ref and not gateway_report:
        run.status = "failed"
        run.error = "执行请求未通过连接器执行网关回报，中心不会直接查询下游引擎"
        db.commit()
        db.refresh(run)
    return run
