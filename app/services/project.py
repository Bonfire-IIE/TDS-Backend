from __future__ import annotations
import hashlib, json, re, uuid
from copy import deepcopy
from app.services import application_template as templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.capability import (
    ConnectorCapability,
    DataResourceBinding,
    PrivacyApplication,
    PrivacyApplicationBinding,
)
from app.models import AppImage, Connector, DataCatalog, DataGrant, DataLineage, DigitalContract, Project, ProjectRun, WorkflowApproval, WorkflowVersion
from app.models.product import DataProduct, DataProductResource
from app.services import usage
from app.services.standard_contract import allowed_app_images, allowed_applications, info, legacy_policy_input

class ProjectError(Exception):
    def __init__(self,message,status_code=400): super().__init__(message); self.message=message; self.status_code=status_code

def _owned(db, connector_id, username):
    c=db.get(Connector,connector_id); return bool(c and c.created_by==username)

def _visible(db, username, operator):
    if operator: return select(Project).order_by(Project.created_at.desc())
    owned_connectors=list(db.scalars(select(Connector).where(Connector.created_by==username)))
    owned_ids=[connector.id for connector in owned_connectors]
    owned_refs={ref for connector in owned_connectors for ref in (connector.id,connector.tds_code) if ref}
    participant_contract_ids=[]
    if owned_refs:
        from app.services.standard_contract import execution_nodes
        for contract in db.scalars(select(DigitalContract)):
            try:
                nodes=execution_nodes(contract.document)
            except Exception:
                continue
            participants={nodes.get("providerNodeId"),nodes.get("consumerNodeId")}
            if owned_refs & {ref for ref in participants if ref}:
                participant_contract_ids.append(contract.contract_id)
    return select(Project).where(or_(
        Project.created_by==username,
        Project.initiator_connector_id.in_(owned_ids),
        Project.contract_id.in_(participant_contract_ids),
    )).order_by(Project.created_at.desc())

def project_domains(db, project):
    contract=db.get(DigitalContract,project.contract_id)
    if not contract: raise ProjectError("项目关联的合约不存在",409)
    # Contract participants are business identifiers in the standard document.
    participants=[]
    try:
        from app.services.standard_contract import execution_nodes
        nodes=execution_nodes(contract.document)
        participants=[nodes.get("providerNodeId"),nodes.get("consumerNodeId")]
    except Exception:
        participants=[]
    connectors=[]
    for ref in dict.fromkeys([x for x in participants if x]):
        c=db.scalar(select(Connector).where(or_(Connector.id==ref,Connector.tds_code==ref)))
        if c: connectors.append(c)
    if not connectors and project.initiator_connector_id:
        c=db.get(Connector,project.initiator_connector_id)
        if c: connectors=[c]
    if any(connector is None for connector in connectors): raise ProjectError("项目关联的连接器不存在",409)
    return connectors

def execution_domains(db, project):
    connectors=list(project_domains(db,project))
    delegation=templates.approved_services(db,project)
    if delegation:
        ids={c.id for c in connectors}
        for p in delegation.scope.get("participants",[]):
            if p["connector_id"] not in ids:
                c=db.get(Connector,p["connector_id"])
                if c: connectors.append(c); ids.add(c.id)
    return connectors

def contract_input_scope(db, project):
    """Business participants and provider resources of the contracted product."""
    from app.services.standard_contract import execution_nodes
    contract = db.get(DigitalContract, project.contract_id)
    if not contract: raise ProjectError("项目关联的合约不存在", 409)
    nodes = execution_nodes(contract.document)
    def resolve(ref):
        connector = db.scalar(select(Connector).where(or_(Connector.id == ref, Connector.tds_code == ref))) if ref else None
        if not connector: raise ProjectError("合约参与方连接器不存在", 409)
        return connector.id
    provider, consumer = resolve(nodes.get("providerNodeId")), resolve(nodes.get("consumerNodeId"))
    resources = set()
    for policy in contract.document.get("contractPolicies", []):
        product_ref = (policy.get("subjectInfo") or {}).get("dataProductId")
        product = db.scalar(select(DataProduct).where(or_(DataProduct.id == product_ref, DataProduct.tds_code == product_ref))) if product_ref else None
        if product:
            resources.update(db.scalars(select(DataProductResource.resource_id).where(DataProductResource.product_id == product.id)))
            if product.resource_id: resources.add(product.resource_id)
    return provider, consumer, resources


def input_representation(resource, binding=None):
    snapshot = dict(binding.metadata_snapshot or {}) if binding else {}
    source = snapshot.get("datasource_type") or resource.datasource_type
    suffix = (resource.relative_uri or "").rsplit(".", 1)
    fmt = str(resource.resource_format or snapshot.get("format") or (suffix[-1] if len(suffix) == 2 else "")).lower() or None
    prepared = (settings.pets_scheduler_mode == "master-lite" and resource.data_type == "table"
                and source in {"localfs", "oss", "sftp", "ftp", "jdbc"}
                and (source == "jdbc" or fmt in {"csv", "tsv", "json", "jsonl", "parquet", "orc"}))
    return source, fmt, "localfs" if prepared else source, "csv" if prepared else fmt


def available_domain_data(db, project, username: str, operator: bool = False):
    connectors=project_domains(db,project)
    provider_id, consumer_id, contract_resources = contract_input_scope(db, project)
    connector_names={c.id:c.name for c in connectors}
    rows=db.scalars(select(DataCatalog).join(
        DataResourceBinding,
        (DataResourceBinding.platform_resource_id==DataCatalog.id)
        & (DataResourceBinding.connector_id==DataCatalog.provider_connector_id),
    ).where(
        or_((DataCatalog.provider_connector_id == provider_id) & DataCatalog.id.in_(contract_resources), DataCatalog.provider_connector_id == consumer_id),
        DataCatalog.status=="published", DataCatalog.deleted_at.is_(None),
        DataResourceBinding.sync_status=="synced",
        DataResourceBinding.connector_resource_ref.is_not(None),
    ).order_by(DataCatalog.name)).all()
    def out(r):
        binding=db.scalar(select(DataResourceBinding).where(DataResourceBinding.platform_resource_id==r.id,DataResourceBinding.connector_id==r.provider_connector_id,DataResourceBinding.sync_status=="synced"))
        source, fmt, input_source, input_format = input_representation(r, binding)
        return {"resource_id":r.id,"domaindata_id":binding.connector_resource_ref if binding else r.id,"domain_id":r.provider_connector_id,
             "connector_id":r.provider_connector_id,"connector_name":connector_names.get(r.provider_connector_id,r.provider_connector_id),"name":r.name,"data_type":r.data_type,
             "datasource_type":source, "format":fmt,
             "input_source_type":input_source, "input_format":input_format,
             "selection_scope":"contract" if r.provider_connector_id == provider_id else "consumer",
             "columns":r.columns,"relative_uri":r.relative_uri}
    return [out(r) for r in rows]

def _ports(app, direction):
    return {x.get("name"):x for x in ((app.io_schema or {}).get(direction,[]) or []) if x.get("name")}

def _party_roles(app):
    roles = {}
    for raw in ((app.party_schema or {}).get("roles") or []):
        role = raw if isinstance(raw, str) else raw.get("name")
        if not role:
            continue
        roles[role] = raw if isinstance(raw, dict) else {"name": role}
    return roles

def get(db,id,username,operator):
    p=db.get(Project,id)
    if not p or not db.execute(_visible(db,username,operator).where(Project.id==id)).scalar_one_or_none(): raise ProjectError("项目不存在或无权访问",404)
    return p

def create(db,username,operator,body):
    c=db.get(DigitalContract,body.contract_id)
    if not c or info(c.document).get("contractStatus") != "filed": raise ProjectError("只能基于已备案合约创建项目",409)
    participants=[]
    try:
        from app.services.standard_contract import execution_nodes
        n=execution_nodes(c.document); participants=[n.get("consumerNodeId"), n.get("providerNodeId")]
    except Exception: pass
    initiator=None
    for ref in participants:
        candidate=db.scalar(select(Connector).where(or_(Connector.id==ref,Connector.tds_code==ref)))
        if candidate and (operator or candidate.created_by==username): initiator=candidate; break
    if not initiator: raise ProjectError("仅合约参与方或运营方可创建项目",403)
    p=Project(name=body.name,description=body.description,contract_id=c.contract_id,initiator_connector_id=initiator.id,status="draft",created_by=username)
    db.add(p)
    db.commit(); db.refresh(p); return p

def validate_workflow(db,project,workflow):
    nodes=workflow.get("nodes"); edges=workflow.get("edges",[])
    if not isinstance(nodes,list) or not nodes: raise ProjectError("编排至少包含一个 AppImage 节点")
    if len(nodes)>128: raise ProjectError("KusciaJob 最多包含 128 个任务")
    ids=[n.get("id") for n in nodes]
    if any(not isinstance(x,str) or not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?",x) or len(x)>40 for x in ids): raise ProjectError("节点 id 须为不超过 40 位的 RFC1123 名称")
    if len(ids)!=len(set(ids)): raise ProjectError("节点 id 必须唯一")
    aliases=[n.get('alias') or n['id'] for n in nodes]
    if any(not isinstance(a,str) or not a or len(a)>63 for a in aliases) or len(aliases)!=len(set(aliases)):
        raise ProjectError("任务别名须为不超过 63 位的唯一字符串")
    parties={x.id for x in execution_domains(db,project)}
    provider_id, consumer_id, contract_resources = contract_input_scope(db, project)
    grant_warnings=[]
    for n in nodes:
        app=templates.snapshot_app(db,n)
        if not app: raise ProjectError(f"节点 {n['id']} 的 AppImage 不存在或已下架")
        if not n.get("template_version") and any(x.get("domain_id") not in {provider_id,consumer_id} for x in n.get("parties",[])):
            raise ProjectError("额外计算服务必须通过获准应用实例参与",403)
        if not isinstance(n.get("parties"),list) or any(x.get("domain_id") not in parties for x in n["parties"]): raise ProjectError(f"节点 {n['id']} 包含非项目参与方")
        deploy_roles={template.get("role","") for template in (app.deploy_templates or [])}
        unsupported={x.get("role","") for x in n["parties"]}-deploy_roles
        if unsupported: raise ProjectError(f"节点 {n['id']} 包含 AppImage 不支持的任务角色: {', '.join(sorted(unsupported))}")
        party_roles=_party_roles(app)
        if party_roles:
            counts={role: 0 for role in party_roles}
            role_domains={role: set() for role in party_roles}
            for party in n["parties"]:
                role=party.get("role")
                if role not in party_roles:
                    raise ProjectError(f"节点 {n['id']} 包含未声明的参与方角色: {role or '未命名'}")
                counts[role]+=1
                role_domains[role].add(party.get("domain_id"))
            for role, definition in party_roles.items():
                minimum=int(definition.get("min", 1 if definition.get("required") else 0) or 0)
                maximum=definition.get("max")
                if counts[role] < minimum:
                    raise ProjectError(f"节点 {n['id']} 的参与方角色 {role} 至少需要 {minimum} 个参与方")
                if maximum is not None and counts[role] > int(maximum):
                    raise ProjectError(f"节点 {n['id']} 的参与方角色 {role} 最多允许 {maximum} 个参与方")
                if len(role_domains[role]) != counts[role]:
                    raise ProjectError(f"节点 {n['id']} 的参与方角色 {role} 不能重复绑定同一连接器")
        inputs=_ports(app,"inputs"); outputs=_ports(app,"outputs")
        parameter_schema=app.parameter_schema or {}
        properties=parameter_schema.get("properties") or {}
        parameters=n.get("parameters") or {}
        for name in parameter_schema.get("required") or []:
            if name not in parameters or parameters[name] is None or parameters[name]=="": raise ProjectError(f"节点 {n['id']} 缺少必填参数 {name}")
        for name,value in parameters.items():
            definition=properties.get(name)
            if not definition: raise ProjectError(f"节点 {n['id']} 包含 AppImage 未声明的参数 {name}")
            expected=definition.get("type")
            valid=(expected=="string" and isinstance(value,str)) or (expected=="number" and isinstance(value,(int,float)) and not isinstance(value,bool)) or (expected=="integer" and isinstance(value,int) and not isinstance(value,bool)) or (expected=="boolean" and isinstance(value,bool)) or (expected=="array" and isinstance(value,list))
            if expected and not valid: raise ProjectError(f"节点 {n['id']} 参数 {name} 类型应为 {expected}")
            if definition.get("enum") and value not in definition["enum"]: raise ProjectError(f"节点 {n['id']} 参数 {name} 不在允许的枚举值中")
        bindings=n.get("input_bindings",[]) or []
        bound_ports=[]
        for input_binding in bindings:
            port=input_binding.get("port")
            if port not in inputs: raise ProjectError(f"节点 {n['id']} 的输入端口 {port or '未命名'} 未在 AppImage 中声明")
            bound_ports.append(port)
            dd_id=input_binding.get("domaindata_id")
            resource_binding=db.scalar(select(DataResourceBinding).where(
                DataResourceBinding.connector_id==input_binding.get("domain_id"),
                DataResourceBinding.connector_resource_ref==dd_id,
                DataResourceBinding.sync_status=="synced",
            )) if dd_id else None
            owner=db.get(DataCatalog,resource_binding.platform_resource_id) if resource_binding else None
            # 数据边产生的中间 DomainData 只在本次运行编译时分配，尚未落库；
            # 其合法性由后面的 data edge 端口类型校验保证。
            if input_binding.get("source_node"):
                raise ProjectError("中间输入由数据连线自动生成，请勿直接填写 source_node")
            if not owner: raise ProjectError(f"节点 {n['id']} 的输入绑定 DomainData 不存在或已下架")
            if owner.status != "published" or owner.deleted_at is not None:
                raise ProjectError(f"节点 {n['id']} 的输入资源已下架或删除")
            if owner.provider_connector_id != resource_binding.connector_id:
                raise ProjectError(f"节点 {n['id']} 的资源不属于绑定连接器")
            if owner.provider_connector_id == provider_id and owner.id not in contract_resources:
                raise ProjectError("供数方只能使用合约产品绑定的数据资源", 403)
            if owner.provider_connector_id not in {provider_id, consumer_id}:
                raise ProjectError("输入资源必须属于合约供数方或用数方", 403)
            input_role=inputs[port].get("role")
            if input_role and party_roles:
                role_domains={x.get("domain_id") for x in n["parties"] if x.get("role")==input_role}
                if input_binding.get("domain_id") not in role_domains:
                    raise ProjectError(f"节点 {n['id']} 的输入端口 {port} 必须绑定角色 {input_role} 对应的连接器")
            # File transport is compatible with image/text catalog classifications.
            # Explicit data_types remain restrictive; formats are checked separately.
            accepted=inputs[port].get("data_types")
            if not accepted:
                kind=inputs[port].get("kind")
                accepted=["file", "image", "text"] if kind=="file" else ([kind] if kind else [])
            if accepted and owner.data_type not in accepted: raise ProjectError(f"节点 {n['id']} 输入端口 {port} 不接受 {owner.data_type} 数据")
            _, _, source_type, data_format = input_representation(owner, resource_binding)
            accepted_sources=inputs[port].get("source_types") or []
            if accepted_sources and "*" not in accepted_sources and source_type not in accepted_sources:
                raise ProjectError(f"节点 {n['id']} 输入端口 {port} 不接受 {source_type} 数据源")
            accepted_formats=inputs[port].get("formats") or []
            if accepted_formats and data_format not in accepted_formats:
                raise ProjectError(f"节点 {n['id']} 输入端口 {port} 不接受 {data_format or '未知'} 格式")
        incoming={e.get("target_handle") for e in edges if e.get("type")=="data" and e.get("target")==n["id"]}
        for name,pdef in inputs.items():
            if pdef.get("required",True) and name not in bound_ports and name not in incoming:
                raise ProjectError(f"节点 {n['id']} 缺少必填输入端口 {name}")
        for binding in n.get("output_bindings",[]) or []:
            if binding.get("port") not in outputs: raise ProjectError(f"节点 {n['id']} 的输出端口 {binding.get('port') or '未命名'} 未在 AppImage 中声明")
            if binding.get("domain_id") not in {x.get("domain_id") for x in n["parties"]}: raise ProjectError(f"节点 {n['id']} 的输出域不是任务参与方")
            output_role=outputs[binding.get("port")].get("role")
            if output_role and party_roles and binding.get("domain_id") not in {x.get("domain_id") for x in n["parties"] if x.get("role")==output_role}:
                raise ProjectError(f"节点 {n['id']} 的输出端口 {binding.get('port')} 必须绑定角色 {output_role} 对应的连接器")
        output_bound={b.get("port") for b in (n.get("output_bindings") or [])}
        for name,pdef in outputs.items():
            if pdef.get("register",True) and name not in output_bound and not any(e.get("type")=="data" and e.get("source")==n["id"] and e.get("source_handle")==name for e in edges):
                raise ProjectError(f"节点 {n['id']} 缺少输出端口 {name} 的 DomainData 配置")
    if grant_warnings and not workflow.get("grant_warning_acknowledged"):
        raise ProjectError("提交前需要确认额外数据授权：" + "；".join(grant_warnings), 409)
    parallelism=workflow.get("max_parallelism",len(nodes))
    if not isinstance(parallelism,int) or not 1<=parallelism<=128: raise ProjectError("max_parallelism 必须在 1..128")
    graph={x:[] for x in ids}; indegree={x:0 for x in ids}; seen_edges=set(); input_sources=set()
    for e in edges:
        a,b=e.get("source"),e.get("target")
        if a not in graph or b not in graph: raise ProjectError("编排边引用了不存在的节点")
        source=nodes[ids.index(a)]
        if source.get("tolerable"): raise ProjectError(f"容错节点 {a} 不能作为其他节点的依赖")
        edge_type=e.get("type","control")
        if edge_type not in ("control","data"): raise ProjectError("边类型只能是 control 或 data")
        if edge_type=="data":
            target=nodes[ids.index(b)]
            input_key=(b,e.get("target_handle"))
            if input_key in input_sources or any(x.get("port")==input_key[1] for x in target.get("input_bindings",[])):
                raise ProjectError("同一输入端口只能有一个数据来源")
            input_sources.add(input_key)
            source_app=templates.snapshot_app(db,source)
            target_app=templates.snapshot_app(db,target)
            output_name=e.get("source_handle"); input_name=e.get("target_handle")
            outputs=(source_app.io_schema or {}).get("outputs",[]) if source_app else []
            inputs=(target_app.io_schema or {}).get("inputs",[]) if target_app else []
            output=next((x for x in outputs if x.get("name")==output_name),None)
            input_port=next((x for x in inputs if x.get("name")==input_name),None)
            if not output or not input_port: raise ProjectError(f"数据边 {a}→{b} 必须连接 AppImage 已声明的输出/输入端口")
            if output.get("kind")!=input_port.get("kind"): raise ProjectError(f"数据边 {a}→{b} 的端口类型不兼容")
            source_role=output.get("role");target_role=input_port.get("role")
            source_domains={p["domain_id"] for p in source["parties"] if not source_role or p.get("role")==source_role}
            target_domains={p["domain_id"] for p in target["parties"] if not target_role or p.get("role")==target_role}
            source_bound=next((p.get("domain_id") for p in source.get("output_bindings",[]) if p.get("port")==output_name),None)
            if source_bound: source_domains={source_bound}
            if len(source_domains)!=1 or not source_domains<=target_domains:
                raise ProjectError(f"数据边 {a}→{b} 必须在同一计算域交接，不能跨域传输")
            if output.get("formats") and input_port.get("formats") and not set(output["formats"]) & set(input_port["formats"]):
                raise ProjectError(f"数据边 {a}→{b} 格式不兼容")
        if (a,b) not in seen_edges:
            seen_edges.add((a,b));graph[a].append(b); indegree[b]+=1
    queue=[x for x in ids if indegree[x]==0]; seen=0
    while queue:
        x=queue.pop(); seen+=1
        for y in graph[x]:
            indegree[y]-=1
            if indegree[y]==0: queue.append(y)
    if seen!=len(ids): raise ProjectError("编排不能包含环")

def submit(db,p,username,workflow):
    if p.created_by!=username: raise ProjectError("仅项目发起方可提交编排",403)
    if any(n.get("template_version") and n.get("detached") is not True for n in workflow.get("nodes",[])):
        raise ProjectError("不能直接提交展开的模板任务；请提交应用实例",422)
    source_workflow=deepcopy(workflow)
    workflow=templates.expand(db,p,workflow)
    validate_workflow(db,p,workflow)
    delegation=templates.approved_services(db,p)
    workflow["delegation_snapshot"] = ({
        "id":delegation.id,"version":delegation.version,"scope":deepcopy(delegation.scope),
        "scope_hash":delegation.scope_hash,"contract_hash":delegation.contract_hash,
        "expires_at":delegation.expires_at.isoformat(),
    } if delegation else None)
    workflow["source_workflow"]=source_workflow
    version=(db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.project_id==p.id)) or 0)+1
    canonical=json.dumps(workflow,sort_keys=True,separators=(",",":"),ensure_ascii=False); digest=hashlib.sha256(canonical.encode()).hexdigest()
    row=WorkflowVersion(project_id=p.id,version=version,workflow=workflow,workflow_hash=digest,status="pending_approval",created_by=username)
    db.add(row); db.flush()
    # 提案-接受(accept)模式：数据提供方发布时已默认同意基准条款，无需再人工审核——
    # 把该"默认同意"作为一条审核数据落库，审核完成判定(参与方一致同意)逻辑保持不变。
    contract=db.get(DigitalContract,p.contract_id)
    if contract and getattr(contract, "mode", None)=="accept":
        provider=project_domains(db,p)[0]
        db.add(WorkflowApproval(workflow_version_id=row.id,connector_id=provider.id,decision="approved",comment="提案-接受模式：数据提供方默认同意",decided_by="system"))
    p.current_version=version; p.status="pending_approval"; db.commit(); db.refresh(row); return row

def approve(db,p,username,operator,body):
    parties={conn.id:conn for conn in project_domains(db,p)}
    cid=body.connector_id
    if not cid:
        # 用户无需选择代表方：自动取其拥有的参与方连接器
        owned=[conn_id for conn_id,conn in parties.items() if conn.created_by==username]
        if not owned: raise ProjectError("您不是本项目参与方连接器的所有者，无法审核",403)
        if len(owned)>1: raise ProjectError("您拥有多个参与方连接器，请指定代表方后审核",400)
        cid=owned[0]
    if cid not in parties: raise ProjectError("该连接器不是合约相关方",403)
    if parties[cid].created_by!=username: raise ProjectError("只能由参与方连接器所有者审核，运营方不能代审",403)
    version=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version==p.current_version))
    if version is None: raise ProjectError("当前没有待审核的编排版本",409)
    if version.status=="approved": raise ProjectError("该编排版本已审核通过，不可重复审核",409)
    old=db.scalar(select(WorkflowApproval).where(WorkflowApproval.workflow_version_id==version.id,WorkflowApproval.connector_id==cid))
    if old: old.decision,old.comment,old.decided_by=body.decision,body.comment,username
    else: db.add(WorkflowApproval(workflow_version_id=version.id,connector_id=cid,decision=body.decision,comment=body.comment,decided_by=username))
    db.flush(); approvals=list(db.scalars(select(WorkflowApproval).where(WorkflowApproval.workflow_version_id==version.id)))
    if body.decision=="rejected": version.status=p.status="rejected"
    elif {x.connector_id for x in approvals if x.decision=="approved"}==set(parties):
        version.status=p.status="approved"
    db.commit(); return version

# ---------- 里程碑①：节点互联（ClusterDomainRoute）----------
def connectivity_pairs(db, project):
    """项目各参与域两两有序对（i→j, i≠j），去重。"""
    ids=list(dict.fromkeys(c.id for c in project_domains(db,project)))
    return [(a,b) for a in ids for b in ids if a!=b]

def _connectivity_context(db, project):
    conns=execution_domains(db,project);targets={}
    for conn in conns:
        caps=list(db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==conn.id,ConnectorCapability.status=="verified").order_by(ConnectorCapability.id)))
        cap=next((c for c in caps if (c.evidence or {}).get("network")),None)
        targets[conn.id]=(cap,(cap.evidence or {}).get("network",{}) if cap else {})
    scope=templates.digest([{ "connector_id":c.id,"status":c.status,"network":targets[c.id][1]} for c in conns])
    return conns,targets,scope

def connectivity_status(db, project):
    from datetime import datetime,timezone,timedelta
    conns,targets,scope=_connectivity_context(db,project);pairs=[]
    for source in conns:
        cap,_=targets[source.id];cache=((cap.evidence or {}).get("connectivity") or {}).get(project.id,{}) if cap else {}
        for target in conns:
            if source.id==target.id:continue
            value=(cache.get("pairs") or {}).get(target.id,{}) if cache.get("scope_hash")==scope else {}
            try:fresh=datetime.fromisoformat(value.get("checked_at","")).replace(tzinfo=timezone.utc)>datetime.now(timezone.utc)-timedelta(minutes=5)
            except (ValueError,TypeError):fresh=False
            state=value.get("state","unknown") if fresh else "unknown"
            pairs.append({**value,"src":source.id,"dst":target.id,"state":state,"status":state,"ready":state=="ready"})
    return {"pairs":pairs,"connected":bool(pairs) and all(p["ready"] for p in pairs),"scope_hash":scope}

def ensure_connectivity(db, project):
    from app.services.execution_dispatch import _post,_endpoint
    from datetime import datetime,timezone
    from app.integrations.kuscia import get_kuscia_client
    from urllib.parse import urlsplit
    conns,targets,scope=_connectivity_context(db,project);identities={};errors={}
    master=get_kuscia_client() if settings.pets_scheduler_mode=="master-lite" else None
    for conn in conns:
        try:
            if conn.status not in ("active","approved"):raise ValueError("连接器未激活")
            identities[conn.id]=_post(_endpoint(targets[conn.id][1].get("connector_endpoint"),conn.id),'project-'+project.id,conn.id,'identity',{'connector_id':conn.id},15)
        except Exception as exc:errors[conn.id]=str(exc)[:400]
    for source in conns:
        cap,network=targets[source.id]
        if not cap:continue
        results={}
        for target in conns:
            if source.id==target.id:continue
            value={"src":source.id,"dst":target.id,"state":"failed","ready":False,"checked_at":datetime.now(timezone.utc).isoformat()}
            try:
                if source.id in errors or target.id in errors:raise ValueError(errors.get(source.id) or errors.get(target.id))
                master_route=None
                if master:
                    gateway=urlsplit(targets[target.id][1].get('gateway_endpoint') or '')
                    src_domain=identities[source.id]['domain_id'];dst_domain=identities[target.id]['domain_id']
                    if not gateway.hostname:raise ValueError('对端网关地址无效')
                    if not master.query_route(src_domain,dst_domain):master.create_cluster_route(src_domain,dst_domain,gateway.hostname,gateway.port or (443 if gateway.scheme=='https' else 80),gateway.scheme=='https')
                    master_route=master.route_status(src_domain,dst_domain)
                    if master_route!='Succeeded':raise ValueError('Master域路由尚未Succeeded: '+str(master_route))
                value=_post(_endpoint(network.get("connector_endpoint"),source.id),'project-'+project.id,source.id,'connectivity',{'connector_id':source.id,'peer_identity':identities[target.id],'gateway_endpoint':targets[target.id][1].get("gateway_endpoint"),'scheduling_mode':settings.pets_scheduler_mode,'master_route_state':master_route},20)
                if value.get('src')!=source.id or value.get('dst')!=target.id or value.get('state') not in {'ready','failed','probing','unknown'}:raise ValueError('互联探测范围无效')
            except Exception as exc:value.update(state='failed',ready=False,reason=str(exc)[:400])
            results[target.id]=value
        evidence=deepcopy(cap.evidence or {});evidence.setdefault('connectivity',{})[project.id]={'scope_hash':scope,'pairs':results};cap.evidence=evidence
    if master:master.close()
    db.commit();return connectivity_status(db,project)

def begin_connectivity_probe(db,project):
    from datetime import datetime,timezone
    conns,targets,scope=_connectivity_context(db,project)
    for source in conns:
        cap,_=targets[source.id]
        if not cap:continue
        evidence=deepcopy(cap.evidence or {})
        evidence.setdefault('connectivity',{})[project.id]={'scope_hash':scope,'pairs':{
            target.id:{'src':source.id,'dst':target.id,'state':'probing','ready':False,'checked_at':datetime.now(timezone.utc).isoformat()}
            for target in conns if target.id!=source.id}}
        cap.evidence=evidence
    db.commit();return connectivity_status(db,project)

def fail_connectivity_probe(db,project,reason):
    conns,targets,scope=_connectivity_context(db,project)
    for conn in conns:
        cap,_=targets[conn.id]
        if not cap:continue
        evidence=deepcopy(cap.evidence or {});cache=(evidence.get('connectivity') or {}).get(project.id,{})
        if cache.get('scope_hash')!=scope:continue
        for value in cache.get('pairs',{}).values():
            if value.get('state')=='probing':value.update(state='failed',ready=False,reason=reason[:400])
        cap.evidence=evidence
    db.commit()

def _runtime_workflow(workflow, appimages, project_id, run_id):
    """Materialize stable output bindings while preserving the abstract DAG."""
    value=json.loads(json.dumps(workflow))
    nodes=value.get("nodes") or []
    by_id={node.get("id"):node for node in nodes}
    output_locations=set()
    for node in nodes:
        app=appimages[node["app_image"]]
        output_ports={str(port.get("name") or ""):port for port in ((app.io_schema or {}).get("outputs") or [])}
        bindings=node.setdefault("output_bindings",[])
        required={edge.get("source_handle") for edge in value.get("edges",[]) or []
                  if edge.get("type")=="data" and edge.get("source")==node.get("id")}
        for name in required:
            if name and not any(item.get("port")==name for item in bindings):
                bindings.append({"port":name,"domain_id":(node.get("parties") or [{}])[0].get("domain_id")})
        for binding in bindings:
            port=str(binding.get("port") or "")
            definition=output_ports.get(port) or {}
            formats=definition.get("formats") or []
            relative=str(binding.get("relative_uri") or "")
            fmt=str(binding.get("format") or "")
            if not fmt and len(formats)==1: fmt=str(formats[0])
            if not fmt and relative.rsplit(".",1)[-1]!=relative: fmt=relative.rsplit(".",1)[-1].lower()
            if not fmt: raise ProjectError(f"节点 {node['id']} 的输出端口 {port} 未声明唯一格式",400)
            binding.setdefault("domaindata_id",f"tds-{run_id[:8]}-{node['id']}-{port}"[:63])
            if definition.get('path_template') is not None:
                try:rendered=templates.output_path(definition['path_template'],project_id,run_id,node['id'],port)
                except templates.TemplateError as exc:raise ProjectError(str(exc),exc.status_code) from exc
                if relative and relative!=rendered:raise ProjectError('不能覆盖应用声明的输出路径',403)
                binding['relative_uri']=rendered
            else:binding.setdefault("relative_uri",f"projects/{project_id}/{run_id}/{node['id']}-{port}.{fmt}")
            location=(binding.get('domain_id'),binding['relative_uri'])
            if location in output_locations:raise ProjectError('同一计算域存在重复输出文件路径',422)
            output_locations.add(location)
            binding["format"]=fmt
    for edge in value.get("edges",[]) or []:
        if edge.get("type")!="data": continue
        source,target=by_id.get(edge.get("source")),by_id.get(edge.get("target"))
        if not source or not target: raise ProjectError("工作流数据边引用不存在的节点",400)
        output=next((item for item in source.get("output_bindings") or []
                     if item.get("port")==edge.get("source_handle")),None)
        if not output: raise ProjectError("工作流数据边缺少上游输出绑定",400)
        bindings=target.setdefault("input_bindings",[])
        if not any(item.get("port")==edge.get("target_handle") for item in bindings):
            bindings.append({"port":edge.get("target_handle"),"domain_id":output.get("domain_id"),
                             "domaindata_id":output["domaindata_id"],"relative_uri":output["relative_uri"],
                             "format":output["format"],"source_node":source["id"],"source_port":output["port"]})
    return value


def _runtime_application(app, application_code=None, application_version=None):
    input_formats={fmt for port in ((app.io_schema or {}).get("inputs") or []) for fmt in (port.get("formats") or [])}
    output_formats={fmt for port in ((app.io_schema or {}).get("outputs") or []) for fmt in (port.get("formats") or [])}
    metadata={**({"input_format":next(iter(input_formats))} if len(input_formats)==1 else {}),
        **({"output_format":next(iter(output_formats))} if len(output_formats)==1 else {}),
        "io_schema":app.io_schema or {},"party_schema":app.party_schema or {},
        "appimage":{"name":app.name,"display_name":app.display_name,"description":app.description,
                    "capability":app.capability,"operations":app.operations or [],
                    "uc_capabilities":app.uc_capabilities or [],"registry_source":app.registry_source,
                    "registry":app.registry,"image_name":app.image_name,"image_tag":app.image_tag,
                    "deploy_templates":app.deploy_templates or [],"config_templates":app.config_templates or {},
                    "job_template":app.job_template or {},"io_schema":app.io_schema or {},
                    "party_schema":app.party_schema or {},"parameter_schema":app.parameter_schema or {},
                    "ui_schema":app.ui_schema or {},"task_input_template":app.task_input_template,
                    "scope":app.scope,"status":app.status}}
    return {"code":application_code or app.name,"version":application_version or "1",
            "implementation_ref":app.name,
            "task_input_template":app.task_input_template,"implementation_metadata":metadata}


def _resolve_application_contract(db, contract, app):
    """Resolve business identity, execution environment, and connector requirements.

    ``PrivacyApplication.execution_env_code`` is the standard contract value
    (for example ``0601``). ``AppImage.capability`` and binding requirements
    describe implementation capabilities exposed by connectors. They are
    deliberately returned separately because they belong to different policy
    dimensions.
    """
    permitted_applications = set(allowed_applications(contract.document))
    permitted_appimages = set(allowed_app_images(contract.document))
    relevant_actions = set(app.operations or ["process"])
    required_environments = {
        str((policy.get("constraints") or {}).get("exec_env") or "").strip().casefold()
        for policy in legacy_policy_input(contract.document)
        if policy.get("effect") == "allow"
        and relevant_actions.intersection((policy.get("actions") or {}).keys())
        and (policy.get("constraints") or {}).get("exec_env")
    }
    if len(required_environments) > 1:
        raise ProjectError(
            f"合约对 AppImage {app.name} 的操作声明了多个执行环境，无法确定运行环境",
            409,
        )
    required_environment = next(iter(required_environments), None)
    bindings = list(db.scalars(select(PrivacyApplicationBinding).where(
        PrivacyApplicationBinding.system_type == "privacy-compute",
        PrivacyApplicationBinding.system_application_ref == app.name,
        PrivacyApplicationBinding.status == "published",
    )))
    for binding in bindings:
        application = db.get(PrivacyApplication, binding.application_code)
        if not application or application.status != "published":
            continue
        application_environment = str(application.execution_env_code or "").strip().casefold()
        environment_matches = not required_environment or application_environment == required_environment
        if environment_matches and (not permitted_applications or application.code in permitted_applications):
            requirements = list(binding.capability_requirements or [])
            if not requirements and app.capability:
                requirements = [app.capability]
            return application.code, application.version, application.execution_env_code, requirements
    if app.name in permitted_applications or (not permitted_applications and app.name in permitted_appimages):
        return app.name, "1", required_environment or app.capability, [app.capability] if app.capability else []
    if permitted_applications or permitted_appimages:
        raise ProjectError(f"AppImage {app.name} 未映射到合约授权的业务应用", 403)
    return app.name, "1", required_environment or app.capability, [app.capability] if app.capability else []

def run(db,p,username):
    if p.created_by!=username or p.status not in ("approved","completed","failed"): raise ProjectError("项目尚未全部审核通过或无执行权限",409)
    version=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version==p.current_version))
    if not connectivity_status(db,p)["connected"]: raise ProjectError("请先完成连接器接入",409)
    if version.workflow.get("applications") or version.workflow.get("detached_applications"):
        current=templates.expand(db,p,version.workflow["source_workflow"])
        # The delegation snapshot is submission-time audit evidence, not
        # compiler output. Compare only the executable document; expand still
        # revalidates current delegation, provenance and locked role bindings.
        expected={k:v for k,v in version.workflow.items() if k not in {"source_workflow", "delegation_snapshot"}}
        if templates.digest(current)!=templates.digest(expected): raise ProjectError("应用绑定发生变化，需要重新确认工作流",409)
    validate_workflow(db, p, version.workflow)
    run_id=str(uuid.uuid4())
    initiator=db.get(Connector,p.initiator_connector_id)
    if not initiator: raise ProjectError("项目发起方连接器不存在",409)
    # 使用控制（M7）：载合约 + 逐 App 校验能力 + OPA 决策 + count 预占。
    c=db.get(DigitalContract,p.contract_id)
    if not c: raise ProjectError("项目关联的合约不存在",409)
    apps=[]; appimages={}; application_contracts={}; seen=set()
    for n in version.workflow.get("nodes",[]):
        name=n.get("app_image")
        if name in seen: continue
        seen.add(name)
        app=templates.snapshot_app(db,n)
        if not app: raise ProjectError(f"节点 AppImage {name} 不存在或已下架",409)
        application_code, application_version, execution_env_code, capability_requirements = _resolve_application_contract(db, c, app)
        appimages[name]=app
        application_contracts[name]=(application_code, application_version, execution_env_code, capability_requirements)
        apps.append({"exec_env":execution_env_code,"application_code":application_code,"app_image":name,
                     "operations":app.operations or ["process"],"uc_capabilities":app.uc_capabilities or []})
    # 操作符合性：AppImage 声明的每个操作都必须在合约授权范围内（只读校验，不动计数器）
    conns=execution_domains(db,p)
    provider,consumer=(project_domains(db,p)+[None,None])[:2]
    if not provider or not consumer: raise ProjectError("项目需要两个已接入的参与方连接器",409)
    authorization_connector=consumer.tds_code or consumer.id
    try:
        for ai in apps:
            denied=usage.check_operations(db,c,username,authorization_connector,ai["operations"],ai["exec_env"],ai["application_code"])
            if denied: raise ProjectError(f"应用 {ai['app_image']} 声明的操作 {denied} 未获合约授权",403)
    except usage.UsageError as e: raise ProjectError(e.message,e.status_code) from e
    required_capabilities=list(dict.fromkeys(
        requirement
        for _, _, _, requirements in application_contracts.values()
        for requirement in requirements
    ))
    targets={}
    for conn in conns:
        capabilities=list(db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==conn.id,ConnectorCapability.status=="verified")))
        by_code={cap.capability_code:cap for cap in capabilities}
        local_apps={n.get("app_image") for n in version.workflow.get("nodes",[]) if any(x.get("domain_id")==conn.id for x in n.get("parties",[]))}
        local_requirements=list(dict.fromkeys(code for name in local_apps for code in application_contracts[name][3]))
        missing=[code for code in local_requirements if code not in by_code]
        if missing: raise ProjectError(f"连接器 {conn.name} 尚未验证应用所需能力: {', '.join(missing)}",409)
        cap=next((cap for cap in capabilities if (cap.evidence or {}).get("network")),None)
        network=(cap.evidence or {}).get("network", {}) if cap else {}
        targets[conn.id]={"endpoint":network.get("execution_endpoint"),"gateway_endpoint":network.get("gateway_endpoint"),"connector_endpoint":network.get("connector_endpoint"),"node_ref":network.get("execution_node_ref"),"storage_ref":network.get("execution_storage_ref"),"portal_browser_url":network.get("portal_browser_url")}
    if version.workflow.get("applications") or version.workflow.get("detached_applications"):
        for inst in version.workflow.get("applications",[])+version.workflow.get("detached_applications",[]):
            template=db.get(templates.ApplicationTemplateVersion,inst["version_id"])
            for group in template.definition.get("distinct_roles",[]):
                role_connectors={}
                for task in template.definition['tasks']:
                    node=next(n for n in version.workflow['nodes'] if n['id']==inst['id']+'-'+task['id'])
                    for ar,rr in task['roles'].items():
                        role_connectors[rr]=next(x['domain_id'] for x in node['parties'] if x['role']==ar)
                domains=[targets[role_connectors[r]]["node_ref"] for r in group]
                if len(set(domains))!=len(domains):raise ProjectError("独立计算角色不能映射到同一 Domain",403)
    if initiator.id != consumer.id:
        raise ProjectError("项目发起方必须是合约约定的用数方连接器",403)
    runtime_workflow=_runtime_workflow(version.workflow,appimages,p.id,run_id)
    refs={}
    for node in runtime_workflow.get("nodes",[]):
        for binding in node.get("input_bindings",[]) or []:
            if binding.get("source_node"): continue
            ref=binding.get("domaindata_id") or binding.get("resource_ref")
            owner=binding.get("connector_id") or binding.get("domain_id")
            if ref and owner:
                refs.setdefault(owner,[])
                if ref not in refs[owner]: refs[owner].append(ref)
    missing_targets=[conn.name for conn in conns if not all(targets[conn.id].get(key) for key in ("endpoint","gateway_endpoint","connector_endpoint","node_ref","storage_ref"))]
    if missing_targets: raise ProjectError(f"连接器尚未完整登记应用执行网关: {', '.join(missing_targets)}",409)

    def resource_descriptor(connector, resource_ref):
        resource_binding=db.scalar(select(DataResourceBinding).where(
            DataResourceBinding.connector_id==connector.id,
            DataResourceBinding.connector_resource_ref==resource_ref,
            DataResourceBinding.sync_status=="synced",
        ))
        if not resource_binding: raise ProjectError(f"连接器 {connector.name} 的输入资源尚未同步: {resource_ref}",409)
        resource=db.get(DataCatalog,resource_binding.platform_resource_id)
        if not resource: raise ProjectError(f"平台数据资源不存在: {resource_binding.platform_resource_id}",409)
        if resource.status != "published" or resource.deleted_at is not None:
            raise ProjectError(f"平台数据资源已下架或删除: {resource.id}",409)
        if settings.pets_scheduler_mode == "master-lite":
            import re
            if not re.fullmatch(r"V?[1-9][0-9]*", str(resource_binding.version or "")):
                raise ProjectError(f"资源「{resource.name}」缺少连接器发布版本，请在所属连接器完成资源登记与公开同步后重新编排", 409)
        snapshot=dict(resource_binding.metadata_snapshot or {})
        # Prefer the current connector-local datasource id.  Older binding
        # snapshots can retain the removed center datasource UUID.
        datasource_id=resource.datasource_id or snapshot.get("datasource_ref")
        suffix=(resource.relative_uri or "").rsplit(".",1)
        metadata={**snapshot,"name":resource.name,"data_type":resource.data_type,"columns":resource.columns or [],
                  "datasource_ref":datasource_id,"connector_datasource_ref":datasource_id,
                  "datasource_type":snapshot.get("datasource_type") or resource.datasource_type,
                  "relative_uri":resource.relative_uri,
                  "format":str(resource.resource_format or snapshot.get("format") or (suffix[-1] if len(suffix)==2 else "")).lower()}
        return {"ref":resource_ref,"platform_resource_id":resource.id,"version":resource_binding.version,"metadata":metadata}

    provider_refs=refs.get(provider.id) or refs.get(provider.tds_code) or []
    consumer_refs=refs.get(consumer.id) or refs.get(consumer.tds_code) or []
    resources=[]
    for connector,connector_refs in ((provider,provider_refs),(consumer,consumer_refs)):
        resources.extend([{"connector_id":connector.id,**resource_descriptor(connector,ref)} for ref in connector_refs])
    provider_ref,consumer_ref=next(iter(provider_refs),None),next(iter(consumer_refs),None)
    provider_resource=next((item for item in resources if item["connector_id"]==provider.id and item["ref"]==provider_ref),None)
    consumer_resource=next((item for item in resources if item["connector_id"]==consumer.id and item["ref"]==consumer_ref),None)
    first_node=(version.workflow.get("nodes") or [{}])[0]
    first_app=first_node.get("app_image")
    app_row=templates.snapshot_app(db,first_node) if first_app else None
    if not app_row: raise ProjectError("工作流首个 AppImage 不存在或已下架",409)
    first_application_code, first_application_version, _, _ = application_contracts[first_app]
    application=_runtime_application(app_row, first_application_code, first_application_version)
    applications={
        name:_runtime_application(app, *application_contracts[name][:2])
        for name,app in appimages.items()
    }
    request={"scheduling_mode":settings.pets_scheduler_mode,"request_id":run_id,"project_id":p.id,"contract_id":p.contract_id,"workflow":runtime_workflow,"initiator_connector_id":p.initiator_connector_id,
             "provider_connector_id":provider.id,"consumer_connector_id":consumer.id,"dispatch_connector_id":p.initiator_connector_id,
             "provider_resource_ref":provider_ref,"consumer_resource_ref":consumer_ref,"provider_resource":provider_resource,"consumer_resource":consumer_resource,
             "resources":resources,"applications":applications,
             "participants":[{"connector_id":c.id,"subject_id":(db.get(templates.ExecutionIdentity,c.id).subject_id if db.get(templates.ExecutionIdentity,c.id) else None),"execution_node_ref":targets[c.id]["node_ref"],"connector_endpoint":targets[c.id]["connector_endpoint"],"gateway_endpoint":targets[c.id]["gateway_endpoint"],"execution_storage_ref":targets[c.id]["storage_ref"]} for c in conns],
             "delegation_snapshot":({"id":templates.approved_services(db,p).id,"scope_hash":templates.approved_services(db,p).scope_hash,
                 "scope":templates.approved_services(db,p).scope,"expires_at":templates.approved_services(db,p).expires_at.isoformat(),
                 "status":"active","service_authorization":"system"} if templates.approved_services(db,p) else None),
             "provider_execution_endpoint":targets[provider.id]["endpoint"],"consumer_execution_endpoint":targets[consumer.id]["endpoint"],
             "provider_gateway_endpoint":targets[provider.id]["gateway_endpoint"],"consumer_gateway_endpoint":targets[consumer.id]["gateway_endpoint"],
             "provider_connector_endpoint":targets[provider.id]["connector_endpoint"],"consumer_connector_endpoint":targets[consumer.id]["connector_endpoint"],
             "provider_execution_node_ref":targets[provider.id]["node_ref"],"consumer_execution_node_ref":targets[consumer.id]["node_ref"],
             "provider_execution_storage_ref":targets[provider.id]["storage_ref"],"consumer_execution_storage_ref":targets[consumer.id]["storage_ref"],
             "application":application,
             "configuration":first_node.get("parameters") or {},"contract_version":c.current_version,"contract_document_hash":c.document_hash}
    if version.workflow.get("applications") or version.workflow.get("detached_applications"):
        final_ports=set()
        for inst in version.workflow.get("applications",[])+version.workflow.get("detached_applications",[]):
            definition=db.get(templates.ApplicationTemplateVersion,inst["version_id"]).definition
            final_ports.update((inst['id']+'-'+port['task'],port['port']) for port in definition.get('outputs',[]))
        request['artifact_plan']=[{'connector_id':out['domain_id'],'node':node['id'],'port':out['port'],
            'relative_uri':out['relative_uri'],'retention':'result' if (node['id'],out['port']) in final_ports else 'temporary'}
            for node in runtime_workflow['nodes'] for out in node.get('output_bindings',[])]
    # Reserve only after all deterministic validation and compilation succeeds;
    # otherwise a rejected run would leak contract usage quota.
    try:
        usage_records=usage.authorize_and_reserve_actions(
            db,c,username,authorization_connector,apps,
        )
    except usage.UsageError as e:
        raise ProjectError(e.message,e.status_code) from e
    snapshot={"compiler_version":"project-dag/v2","workflow_hash":version.workflow_hash,
              "execution_snapshot":{"compiler_version":"project-dag/v2","workflow_hash":version.workflow_hash,
                                    "workflow":runtime_workflow,"participants":request["participants"]},
              "result_guidance":{"kind":"application_output","portal_directory":"/connectors",
                                 "portal_browser_urls":{cid:target["portal_browser_url"] for cid,target in targets.items() if target.get("portal_browser_url")},"outputs":[a for a in request.get("artifact_plan",[]) if a.get("retention")=="result"],
                                 "message":"执行完成后从参与方 Portal 的执行结果页面查看应用输出；平台仅保存结果摘要。"},
              "execution_request":request,"usage_record_ids":[record.id for record in usage_records]}
    row=ProjectRun(id=run_id,project_id=p.id,workflow_version_id=version.id,kuscia_job_id="exec-"+run_id,status="pending-dispatch",job_snapshot=snapshot,created_by=username)
    try:
        db.add(row); p.status="running"; db.commit(); db.refresh(row)
        usage.consume_many(db,usage_records,run_id)
    except Exception:
        db.rollback()
        usage.release_many(db,usage_records,"运行实例创建失败")
        raise
    return row

def sync_run(db,p,row):
    # Active runs are reconciled by the worker. Explicit refresh can also enrich
    # completed runs created before task progress was persisted.
    from app.services.master_execution import refresh_task_progress
    refresh_task_progress(row.id)
    db.refresh(row)
    return row

def _register_outputs(db,project,row):
    # Output registration is performed by the connector resource adapter after
    # the downstream engine reports completion. The center stores no engine
    # DomainData identifiers.
    return None
