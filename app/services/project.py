from __future__ import annotations
import hashlib, json, re, uuid
from urllib.parse import urlparse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.identifier import gen_data_code
from app.integrations.kuscia import KusciaError, get_kuscia_client
from app.models import AppImage, Connector, DataCatalog, DataGrant, DataLineage, DataProduct, DataSource, DigitalContract, Project, ProjectRun, WorkflowApproval, WorkflowVersion
from app.services import usage
from app.services.idempotency import execution_lock
from app.services.audit import append as audit_append, contract_stream

class ProjectError(Exception):
    def __init__(self,message,status_code=400): super().__init__(message); self.message=message; self.status_code=status_code

def _owned(db, connector_id, username):
    c=db.get(Connector,connector_id); return bool(c and c.created_by==username)

def _visible(db, username, operator):
    if operator: return select(Project).order_by(Project.created_at.desc())
    owned=select(Connector.id).where(Connector.created_by==username)
    contracts=select(DigitalContract.contract_id).where(or_(DigitalContract.provider_connector_id.in_(owned),DigitalContract.consumer_connector_id.in_(owned)))
    return select(Project).where(or_(Project.created_by==username,Project.contract_id.in_(contracts))).order_by(Project.created_at.desc())

def project_domains(db, project):
    contract=db.get(DigitalContract,project.contract_id)
    if not contract: raise ProjectError("项目关联的合约不存在",409)
    connector_ids=dict.fromkeys((contract.provider_connector_id,contract.consumer_connector_id))
    connectors=[db.get(Connector,connector_id) for connector_id in connector_ids]
    if any(connector is None for connector in connectors): raise ProjectError("项目关联的连接器不存在",409)
    return connectors

def available_domain_data(db, project, username: str, operator: bool = False):
    connector_ids=[c.id for c in project_domains(db,project)]
    contract=db.get(DigitalContract, project.contract_id)
    product=db.get(DataProduct, contract.product_id) if contract else None
    contracted_resource_ids={product.resource_id} if product and product.resource_id else set()
    owned_connector_ids={c.id for c in project_domains(db,project) if c.created_by == username}
    rows=db.scalars(select(DataCatalog).where(
        DataCatalog.provider_connector_id.in_(connector_ids),
        DataCatalog.status=="registered", DataCatalog.deleted_at.is_(None),
        DataCatalog.kuscia_domaindata_id.is_not(None),
    ).where(
        DataCatalog.id.in_(contracted_resource_ids) | DataCatalog.provider_connector_id.in_(owned_connector_ids) if not operator else True
    ).order_by(DataCatalog.kuscia_domain_id,DataCatalog.name)).all()
    def out(r):
        ds=db.get(DataSource,r.datasource_id) if r.datasource_id!="default-data-source" else None
        suffix=(r.relative_uri or "").rsplit(".",1)
        return {"resource_id":r.id,"domaindata_id":r.kuscia_domaindata_id,"domain_id":r.kuscia_domain_id,
             "connector_id":r.provider_connector_id,"name":r.name,"data_type":r.data_type,
             "datasource_type":ds.type if ds else "localfs","format":suffix[-1].lower() if len(suffix)==2 else None,
             "columns":r.columns,"relative_uri":r.relative_uri}
    return [out(r) for r in rows]

def _ports(app, direction):
    return {x.get("name"):x for x in ((app.io_schema or {}).get(direction,[]) or []) if x.get("name")}

def get(db,id,username,is_admin):
    if is_admin: raise ProjectError("管理员不可进入项目工作台",403)
    p=db.get(Project,id)
    if not p or not db.execute(_visible(db,username,False).where(Project.id==id)).scalar_one_or_none(): raise ProjectError("项目不存在或无权访问",404)
    return p

def create(db,username,operator,body):
    c=db.get(DigitalContract,body.contract_id)
    if not c or c.status!="filed": raise ProjectError("只能基于已备案合约创建项目",409)
    if not operator and not _owned(db,c.consumer_connector_id,username): raise ProjectError("仅合约用数方或运营方可创建项目",403)
    p=Project(name=body.name,description=body.description,contract_id=c.contract_id,initiator_connector_id=c.consumer_connector_id,status="draft",created_by=username)
    db.add(p); db.flush()
    audit_append(db,event_type="project.created",stream_id=contract_stream(c.contract_id),resource_type="project",resource_id=p.id,actor={"subject":username},payload={"contract_id":c.contract_id,"project_id":p.id,"status":p.status})
    db.commit(); db.refresh(p); return p

def validate_workflow(db,project,workflow):
    nodes=workflow.get("nodes"); edges=workflow.get("edges",[])
    if not isinstance(nodes,list) or not nodes: raise ProjectError("编排至少包含一个 AppImage 节点")
    if len(nodes)>128: raise ProjectError("KusciaJob 最多包含 128 个任务")
    ids=[n.get("id") for n in nodes]
    if any(not isinstance(x,str) or not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?",x) or len(x)>40 for x in ids): raise ProjectError("节点 id 须为不超过 40 位的 RFC1123 名称")
    if len(ids)!=len(set(ids)): raise ProjectError("节点 id 必须唯一")
    parties={x.kuscia_domain_id for x in project_domains(db,project)}
    grant_warnings=[]
    for n in nodes:
        app=db.scalar(select(AppImage).where(AppImage.name==n.get("app_image"),AppImage.status=="registered"))
        if not app: raise ProjectError(f"节点 {n['id']} 的 AppImage 不存在或已下架")
        if not isinstance(n.get("parties"),list) or any(x.get("domain_id") not in parties for x in n["parties"]): raise ProjectError(f"节点 {n['id']} 包含非项目参与方")
        deploy_roles={template.get("role","") for template in (app.deploy_templates or [])}
        unsupported={x.get("role","") for x in n["parties"]}-deploy_roles
        if unsupported: raise ProjectError(f"节点 {n['id']} 包含 AppImage 不支持的任务角色: {', '.join(sorted(unsupported))}")
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
        for binding in bindings:
            port=binding.get("port")
            if port not in inputs: raise ProjectError(f"节点 {n['id']} 的输入端口 {port or '未命名'} 未在 AppImage 中声明")
            bound_ports.append(port)
            dd_id=binding.get("domaindata_id")
            owner=db.scalar(select(DataCatalog).where(DataCatalog.kuscia_domaindata_id==dd_id,DataCatalog.status=="registered",DataCatalog.deleted_at.is_(None))) if dd_id else None
            # 数据边产生的中间 DomainData 只在本次运行编译时分配，尚未落库；
            # 其合法性由后面的 data edge 端口类型校验保证。
            if binding.get("source_node"):
                continue
            if not owner: raise ProjectError(f"节点 {n['id']} 的输入绑定 DomainData 不存在或已下架")
            if owner.kuscia_domain_id != binding.get("domain_id"):
                raise ProjectError(f"节点 {n['id']} 的 DomainData 不属于绑定域 {binding.get('domain_id')}")
            if binding.get("grant_required") or owner.kuscia_domain_id != project_domains(db,project)[0].kuscia_domain_id:
                grant_warnings.append(f"节点 {n['id']} 输入 {binding.get('port') or '未命名'} 需要额外跨域数据授权（{owner.kuscia_domain_id} → {binding.get('domain_id')}）")
            accepted=inputs[port].get("data_types") or ([inputs[port].get("kind")] if inputs[port].get("kind") else [])
            if accepted and owner.data_type not in accepted: raise ProjectError(f"节点 {n['id']} 输入端口 {port} 不接受 {owner.data_type} 数据")
            ds=db.get(DataSource,owner.datasource_id) if owner.datasource_id!="default-data-source" else None
            source_type=ds.type if ds else "localfs"
            accepted_sources=inputs[port].get("source_types") or []
            if accepted_sources and "*" not in accepted_sources and source_type not in accepted_sources:
                raise ProjectError(f"节点 {n['id']} 输入端口 {port} 不接受 {source_type} 数据源")
            suffix=(owner.relative_uri or "").rsplit(".",1)
            data_format=suffix[-1].lower() if len(suffix)==2 else None
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
        output_bound={b.get("port") for b in (n.get("output_bindings") or [])}
        for name,pdef in outputs.items():
            if pdef.get("register",True) and name not in output_bound and not any(e.get("type")=="data" and e.get("source")==n["id"] and e.get("source_handle")==name for e in edges):
                raise ProjectError(f"节点 {n['id']} 缺少输出端口 {name} 的 DomainData 配置")
    if grant_warnings and not workflow.get("grant_warning_acknowledged"):
        raise ProjectError("提交前需要确认额外数据授权：" + "；".join(grant_warnings), 409)
    parallelism=workflow.get("max_parallelism",len(nodes))
    if not isinstance(parallelism,int) or not 1<=parallelism<=128: raise ProjectError("max_parallelism 必须在 1..128")
    graph={x:[] for x in ids}; indegree={x:0 for x in ids}; seen_edges=set()
    for e in edges:
        a,b=e.get("source"),e.get("target")
        if a not in graph or b not in graph: raise ProjectError("编排边引用了不存在的节点")
        if (a,b) in seen_edges: continue
        seen_edges.add((a,b))
        source=nodes[ids.index(a)]
        if source.get("tolerable"): raise ProjectError(f"容错节点 {a} 不能作为其他节点的依赖")
        edge_type=e.get("type","control")
        if edge_type not in ("control","data"): raise ProjectError("边类型只能是 control 或 data")
        if edge_type=="data":
            target=nodes[ids.index(b)]
            source_app=db.scalar(select(AppImage).where(AppImage.name==source.get("app_image")))
            target_app=db.scalar(select(AppImage).where(AppImage.name==target.get("app_image")))
            output_name=e.get("source_handle"); input_name=e.get("target_handle")
            outputs=(source_app.io_schema or {}).get("outputs",[]) if source_app else []
            inputs=(target_app.io_schema or {}).get("inputs",[]) if target_app else []
            output=next((x for x in outputs if x.get("name")==output_name),None)
            input_port=next((x for x in inputs if x.get("name")==input_name),None)
            if not output or not input_port: raise ProjectError(f"数据边 {a}→{b} 必须连接 AppImage 已声明的输出/输入端口")
            if output.get("kind")!=input_port.get("kind"): raise ProjectError(f"数据边 {a}→{b} 的端口类型不兼容")
        graph[a].append(b); indegree[b]+=1
    queue=[x for x in ids if indegree[x]==0]; seen=0
    while queue:
        x=queue.pop(); seen+=1
        for y in graph[x]:
            indegree[y]-=1
            if indegree[y]==0: queue.append(y)
    if seen!=len(ids): raise ProjectError("编排不能包含环")

def submit(db,p,username,workflow):
    if p.created_by!=username: raise ProjectError("仅项目发起方可提交编排",403)
    validate_workflow(db,p,workflow)
    version=(db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.project_id==p.id)) or 0)+1
    canonical=json.dumps(workflow,sort_keys=True,separators=(",",":"),ensure_ascii=False); digest=hashlib.sha256(canonical.encode()).hexdigest()
    row=WorkflowVersion(project_id=p.id,version=version,workflow=workflow,workflow_hash=digest,status="pending_approval",created_by=username)
    db.add(row); db.flush()
    # 提案-接受(accept)模式：数据提供方发布时已默认同意基准条款，无需再人工审核——
    # 把该"默认同意"作为一条审核数据落库，审核完成判定(参与方一致同意)逻辑保持不变。
    contract=db.get(DigitalContract,p.contract_id)
    if contract and contract.mode=="accept":
        db.add(WorkflowApproval(workflow_version_id=row.id,connector_id=contract.provider_connector_id,decision="approved",comment="提案-接受模式：数据提供方默认同意",decided_by="system"))
    p.current_version=version; p.status="pending_approval"
    audit_append(db,event_type="project.workflow.submitted",stream_id=contract_stream(p.contract_id),resource_type="workflow_version",resource_id=row.id,actor={"subject":username},payload={"contract_id":p.contract_id,"project_id":p.id,"version":version,"workflow_hash":digest,"status":row.status})
    db.commit(); db.refresh(row); return row

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
    audit_append(db,event_type="project.workflow.approved" if body.decision=="approved" else "project.workflow.rejected",stream_id=contract_stream(p.contract_id),resource_type="workflow_version",resource_id=version.id,actor={"subject":username},payload={"contract_id":p.contract_id,"project_id":p.id,"version":version.version,"connector_id":cid,"decision":body.decision,"status":version.status})
    db.commit(); return version

def _render(value, context):
    if isinstance(value,dict): return {k:_render(v,context) for k,v in value.items()}
    if isinstance(value,list): return [_render(v,context) for v in value]
    if not isinstance(value,str): return value
    full=re.fullmatch(r"\{\{\s*([^{}]+?)\s*\}\}",value)
    def resolve(path):
        cur=context
        for part in path.strip().split("."):
            if not isinstance(cur,dict) or part not in cur: raise ProjectError(f"taskInputConfig 模板变量不存在: {path}")
            cur=cur[part]
        return cur
    if full: return resolve(full.group(1))
    def repl(m):
        cur=resolve(m.group(1))
        if isinstance(cur,(dict,list)): raise ProjectError(f"taskInputConfig 对象或数组变量只能作为完整值使用: {m.group(1)}")
        return "" if cur is None else str(cur)
    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}",repl,value)

def compile_job(db, version, initiator_domain, project_id, run_id):
    wf=json.loads(json.dumps(version.workflow)); dependencies={n["id"]:[] for n in wf["nodes"]}
    for e in wf.get("edges",[]):
        if e["source"] not in dependencies[e["target"]]: dependencies[e["target"]].append(e["source"])
    job_id="tds-project-"+uuid.uuid4().hex[:12]
    by_id={n["id"]:n for n in wf["nodes"]}
    # 先为显式输出和数据边输出分配稳定 DomainData ID/URI，再注入下游输入绑定。
    for n in wf["nodes"]:
        bindings=n.setdefault("output_bindings",[])
        required_ports={e.get("source_handle") for e in wf.get("edges",[]) if e.get("type")=="data" and e.get("source")==n["id"]}
        for port in required_ports:
            if port and not any(b.get("port")==port for b in bindings):
                bindings.append({"port":port,"domain_id":(n.get("parties") or [{}])[0].get("domain_id",initiator_domain)})
        for b in bindings:
            b.setdefault("domaindata_id",f"tds-{run_id[:8]}-{n['id']}-{b['port']}"[:63])
            b.setdefault("relative_uri",f"projects/{project_id}/{run_id}/{n['id']}-{b['port']}.csv")
    for e in wf.get("edges",[]):
        if e.get("type")!="data": continue
        source=by_id[e["source"]]; target=by_id[e["target"]]
        output=next(b for b in source["output_bindings"] if b.get("port")==e.get("source_handle"))
        bindings=target.setdefault("input_bindings",[])
        if not any(b.get("port")==e.get("target_handle") for b in bindings):
            bindings.append({"port":e.get("target_handle"),"domain_id":output["domain_id"],"domaindata_id":output["domaindata_id"],"source_node":source["id"],"source_port":output["port"]})
    tasks=[]
    for n in wf["nodes"]:
        app=db.scalar(select(AppImage).where(AppImage.name==n["app_image"]))
        inputs={}
        for b in n.get("input_bindings") or []:
            catalog=db.scalar(select(DataCatalog).where(DataCatalog.kuscia_domain_id==b.get("domain_id"),DataCatalog.kuscia_domaindata_id==b.get("domaindata_id"),DataCatalog.deleted_at.is_(None)))
            if not catalog:
                # 数据边的输入来自上游任务输出，尚未成为平台目录行；
                # 仍构造完整的模板上下文，使用默认本地文件数据源端点。
                if b.get("source_node"):
                    default_path = "/home/kuscia/var/storage/data"
                    inputs[b["port"]] = {
                        **b, "relative_uri": b.get("relative_uri") or
                        f"projects/{project_id}/{run_id}/{b.get('source_node')}-{b.get('source_port')}.csv",
                        "relative_url": b.get("relative_uri"), "prefix": default_path,
                        "datasource": {"id": "default-data-source", "type": "localfs",
                                       "name": "default-data-source", "uri": default_path,
                                       "prefix": default_path, "info": {"path": default_path}},
                    }
                else:
                    inputs[b["port"]]=dict(b)
                continue
            ds=db.get(DataSource,catalog.datasource_id) if catalog.datasource_id!="default-data-source" else None
            suffix=(catalog.relative_uri or "").rsplit(".",1)
            # default-data-source 是 Kuscia/Lite 内置本地文件源，不在平台表中；
            # 仍需向 AppImage 模板暴露与显式 localfs 相同的 endpoint 信息。
            default_path = "/home/kuscia/var/storage/data"
            safe_info={k:v for k,v in (ds.info or {}).items() if k.lower() not in {"access_key_id","access_key_secret","secret","password","token","private_key","ak","sk"}} if ds else {"path": default_path}
            ds_uri = ds.uri if ds else default_path
            inputs[b["port"]]={**b,"resource_id":catalog.id,"name":catalog.name,"data_type":catalog.data_type,
                "format":suffix[-1].lower() if len(suffix)==2 else None,"columns":catalog.columns,"relative_uri":catalog.relative_uri,
                "relative_url":catalog.relative_uri,
                "prefix": ds_uri,
                "datasource":{"id":ds.kuscia_datasource_id if ds else "default-data-source","type":ds.type if ds else "localfs",
                              "name":ds.name if ds else "default-data-source","uri":ds_uri,"prefix":ds_uri,"info":safe_info}}
        outputs={}
        for b in n.get("output_bindings") or []:
            outputs[b["port"]]={**b,"relative_url":b.get("relative_uri"),"prefix":"/home/kuscia/var/storage/data",
                                 "datasource":{"id":"default-data-source","type":"localfs","name":"default-data-source",
                                               "uri":"/home/kuscia/var/storage/data","prefix":"/home/kuscia/var/storage/data",
                                               "info":{"path":"/home/kuscia/var/storage/data"}}}
        template=app.task_input_template if app else None
        if template:
            rendered=_render(template,{"project":{"id":project_id},"run":{"id":run_id},"task":{"id":n["id"]},"inputs":inputs,"outputs":outputs,"parameters":n.get("parameters") or {}})
            task_config=json.dumps(rendered,separators=(",",":"),ensure_ascii=False)
        else: task_config=n.get("task_input_config","")
        if not isinstance(task_config,str): raise ProjectError(f"节点 {n['id']} 的 task_input_config 必须是字符串")
        task={"task_id":f"{job_id}-{n['id']}","alias":n.get("alias",n["id"]),"app_image":n["app_image"],"task_input_config":task_config,"parties":[{"domain_id":x["domain_id"],"role":x.get("role","")} for x in n["parties"]]}
        for key in ("priority","tolerable","schedule_config"):
            if key in n: task[key]=n[key]
        # Kuscia 多任务依赖校验按 task alias 解析，而不是按完整 taskID。
        # taskID 仍保持 job 前缀以保证集群内唯一，dependencies 使用上游 alias。
        if dependencies[n["id"]]:
            task["dependencies"] = [by_id[x].get("alias", x) for x in dependencies[n["id"]]]
        tasks.append(task)
    return {"job_id":job_id,"initiator":initiator_domain,"schedule_mode":wf.get("schedule_mode","Strict"),"max_parallelism":wf.get("max_parallelism",len(tasks)),"tasks":tasks}, wf

# ---------- 里程碑①：节点互联（ClusterDomainRoute）----------
def connectivity_pairs(db, project):
    """项目各参与域两两有序对（i→j, i≠j），去重。"""
    ids=list(dict.fromkeys(c.kuscia_domain_id for c in project_domains(db,project)))
    return [(a,b) for a in ids for b in ids if a!=b]

def connectivity_status(db, project):
    """逐对查询 route_status，返回连通概览；Kuscia 异常时该对视为未连通，不抛。"""
    client=get_kuscia_client(); pairs=[]
    for src,dst in connectivity_pairs(db,project):
        try: status=client.route_status(src,dst)
        except KusciaError: status=None
        pairs.append({"src":src,"dst":dst,"status":status,"ready":status=="Succeeded"})
    return {"pairs":pairs,"connected":all(x["ready"] for x in pairs)}

def _route_endpoint(conn):
    """对端连接器的物理路由 endpoint：host 取自登记的 lite_api_endpoint，port 取网关端口 auth_port。

    容器名(kuscia_lite_ctr_prefix+域)仅同机 docker 网络内可达；跨机节点必须用
    物理地址 host:auth_port（auth_port 为 Lite 网关 1080 发布到宿主机的端口）。
    """
    raw=conn.lite_api_endpoint or ""
    host=urlparse(raw).hostname or raw.split("//")[-1].split(":")[0].split("/")[0]
    port=conn.auth_port or 1080
    return (host or None), port

def ensure_connectivity(db, project):
    """按对端连接器登记的物理地址建立 ClusterDomainRoute，返回建后的连通状态。

    已 Succeeded 的路由跳过；缺失或 Failed 的先删后按正确物理地址重建
    （create 幂等无法更新已存在路由的 endpoint）。
    """
    client=get_kuscia_client()
    conns={c.kuscia_domain_id:c for c in project_domains(db,project)}
    for src,dst in connectivity_pairs(db,project):
        dst_conn=conns.get(dst)
        if not dst_conn: raise ProjectError(f"目标连接器 {dst} 不存在，无法建立互联",409)
        host,port=_route_endpoint(dst_conn)
        if not host: raise ProjectError(f"连接器 {dst} 未登记可达地址(lite_api_endpoint)，无法建立互联",409)
        try:
            if client.route_status(src,dst)=="Succeeded": continue
        except KusciaError: pass
        try:
            client.delete_route(src,dst)
            client.create_cluster_route(src,dst,dst_host=host,port=port)
        except KusciaError as e: raise ProjectError(f"建立节点互联失败: {e}",502) from e
    return connectivity_status(db,project)

# ---------- grant 生命周期（跨域 DomainDataGrant）----------
def _grant_plan(db, workflow, project):
    """遍历工作流节点，产出需要建立的授权项 (owner_domain, domaindata_id, grantee)，去重。"""
    plan=[]
    for n in workflow.get("nodes",[]):
        parties=[x.get("domain_id") for x in n.get("parties",[])]
        for binding in n.get("input_bindings") or []:
            owner=binding.get("domain_id"); dd=binding.get("domaindata_id")
            for party in parties:
                if party and party!=owner: plan.append((owner,dd,party))
    return list(dict.fromkeys(plan))

def ensure_grants_for_run(db, run_id, plan):
    """按 plan 建立缺失的授权并落 DataGrant；已有 active 记录则跳过。"""
    client=get_kuscia_client()
    for owner,dd,grantee in plan:
        existing=db.scalar(select(DataGrant).where(DataGrant.domain_id==owner,DataGrant.domaindata_id==dd,DataGrant.grant_domain==grantee,DataGrant.status=="active"))
        if existing: continue
        try: gid=client.create_domaindatagrant(owner,dd,grantee)
        except KusciaError as e: raise ProjectError(f"建立数据授权失败: {e}",502) from e
        db.add(DataGrant(project_run_id=run_id,domain_id=owner,domaindata_id=dd,grant_domain=grantee,kuscia_grant_id=gid,status="active"))
    db.commit()

def revoke_grants_for_run(db, run_id):
    """回收某次运行建立的所有 active 授权（best-effort，异常吞掉）。"""
    client=get_kuscia_client()
    for g in db.scalars(select(DataGrant).where(DataGrant.project_run_id==run_id,DataGrant.status=="active")):
        if g.kuscia_grant_id:
            try: client.delete_domaindatagrant(g.domain_id,g.kuscia_grant_id)
            except Exception: pass
        g.status="revoked"; g.revoked_at=func.now()
    db.commit()

def run(db,p,username,idempotency_key):
    with execution_lock(db, f"project:{p.id}", idempotency_key):
        return _run_locked(db,p,username,idempotency_key)

def _run_locked(db,p,username,idempotency_key):
    existing=db.scalar(select(ProjectRun).where(ProjectRun.project_id==p.id,ProjectRun.idempotency_key==idempotency_key))
    if existing: return existing
    if p.created_by!=username or p.status not in ("approved","completed","failed"): raise ProjectError("项目尚未全部审核通过或无执行权限",409)
    version=db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id==p.id,WorkflowVersion.version==p.current_version))
    # 里程碑①：先校验节点互联，链路未全部连通不得执行。
    if not connectivity_status(db,p)["connected"]: raise ProjectError("请先完成节点互联（链路未全部连通）",409)
    run_id=str(uuid.uuid4())
    initiator=db.get(Connector,p.initiator_connector_id)
    if not initiator: raise ProjectError("项目发起方连接器不存在",409)
    # 使用控制（M7）：载合约 + 逐 App 校验能力 + OPA 决策 + count 预占。
    c=db.get(DigitalContract,p.contract_id)
    if not c: raise ProjectError("项目关联的合约不存在",409)
    product=db.get(DataProduct,c.product_id)
    apps=[]; seen=set()
    for n in version.workflow.get("nodes",[]):
        name=n.get("app_image")
        if name in seen: continue
        seen.add(name)
        app=db.scalar(select(AppImage).where(AppImage.name==name,AppImage.status=="registered"))
        if not app: raise ProjectError(f"节点 AppImage {name} 不存在或已下架",409)
        if c.allowed_appimages and name not in c.allowed_appimages:
            raise ProjectError(f"应用 {name} 不在合约允许的能力列表内",403)
        apps.append({"exec_env":app.capability,"app_image":name,"operations":app.operations or ["process"],"uc_capabilities":app.uc_capabilities or []})
    # 操作符合性：AppImage 声明的每个操作都必须在合约授权范围内（只读校验，不动计数器）
    try:
        for ai in apps:
            denied=usage.check_operations(db,c,username,p.initiator_connector_id,ai["operations"],ai["exec_env"],ai["app_image"])
            if denied:
                details = "；".join(f"{x['action']}：{x['reason']}" for x in denied)
                raise ProjectError(f"应用 {ai['app_image']} 不满足合约授权条件：{details}",403)
    except usage.UsageError as e: raise ProjectError(e.message,e.status_code) from e
    try: usage_records=usage.authorize_and_reserve_actions(db,c,username,p.initiator_connector_id,apps)
    except usage.UsageError as e: raise ProjectError(e.message,e.status_code) from e
    # 建 CDR（幂等再确认）；失败释放预占。
    try: ensure_connectivity(db,p)
    except ProjectError as e: usage.release_many(db,usage_records,f"建立节点互联失败: {e.message}"); raise
    job,compiled_workflow=compile_job(db,version,initiator.kuscia_domain_id,p.id,run_id)
    # 建 grant；失败释放预占。
    plan=_grant_plan(db,version.workflow,p)
    try: ensure_grants_for_run(db,run_id,plan)
    except ProjectError as e: usage.release_many(db,usage_records,f"建立数据授权失败: {e.message}"); raise
    # 提交 KusciaJob；失败释放预占并回收授权。
    try: get_kuscia_client().create_job(job)
    except KusciaError as e:
        usage.release_many(db,usage_records,f"提交 KusciaJob 失败: {e}"); revoke_grants_for_run(db,run_id)
        raise ProjectError(f"提交 KusciaJob 失败: {e}",502) from e
    snapshot={"compiler_version":"project-dag/v2","workflow_hash":version.workflow_hash,"kuscia_job":job,"usage_record_ids":[r.id for r in usage_records],"obligations":{r.action:r.obligations or [] for r in usage_records},"workflow":compiled_workflow}
    row=ProjectRun(id=run_id,project_id=p.id,workflow_version_id=version.id,kuscia_job_id=job["job_id"],status="running",job_snapshot=snapshot,created_by=username,idempotency_key=idempotency_key)
    db.add(row); p.status="running"; db.flush()
    audit_append(db,event_type="project.run.submitted",stream_id=contract_stream(p.contract_id),resource_type="project_run",resource_id=row.id,actor={"subject":username},payload={"contract_id":p.contract_id,"project_id":p.id,"run_id":row.id,"workflow_version_id":version.id,"kuscia_job_id":row.kuscia_job_id,"usage_record_ids":[r.request_id for r in usage_records],"idempotency_key":idempotency_key})
    db.commit(); db.refresh(row)
    usage.consume_many(db,usage_records,run_id)
    return row

def sync_run(db,p,row):
    if row.status in ("succeeded","failed"): return row
    try: data=get_kuscia_client().query_job(row.kuscia_job_id); status=data.get("status",{})
    except KusciaError as e: row.failure_info={"source":"kuscia_master","message":str(e)}; db.commit(); return row
    state=status.get("state") or status.get("phase"); row.status="succeeded" if state=="Succeeded" else "failed" if state in ("Failed","Cancelled","ApprovalReject") else "running"
    task_status=status.get("task_status") or status.get("taskStatus") or {}
    summary={"source":"kuscia_master","phase":state,"reason":status.get("reason"),"message":status.get("err_msg") or status.get("message"),"task_status":task_status,"conditions":status.get("conditions") or [],"party_task_create_status":status.get("party_task_create_status") or status.get("partyTaskCreateStatus") or {}}
    if row.status=="failed": row.failure_info={**summary,"message":summary["message"] or "执行失败","code":state}
    elif row.status=="running": row.failure_info=summary
    else: row.failure_info=None
    if row.status in ("succeeded","failed"):
        p.status="completed" if row.status=="succeeded" else "failed"
        audit_append(db,event_type="project.run.completed" if row.status=="succeeded" else "project.run.failed",stream_id=contract_stream(p.contract_id),resource_type="project_run",resource_id=row.id,payload={"contract_id":p.contract_id,"project_id":p.id,"run_id":row.id,"kuscia_job_id":row.kuscia_job_id,"status":row.status,"failure_info":row.failure_info})
    db.commit()
    if row.status=="failed": usage.compensate_many(db,(row.job_snapshot or {}).get("usage_record_ids") or [],f"项目运行失败: {state}")
    if row.status=="succeeded": _register_outputs(db,p,row)
    if row.status in ("succeeded","failed"): revoke_grants_for_run(db,row.id)  # 回收该 run 的授权（幂等、best-effort）
    db.refresh(row); return row

def _register_outputs(db,project,row):
    wf=(row.job_snapshot or {}).get("workflow") or {}
    for node in wf.get("nodes",[]):
        inputs=[]
        for b in node.get("input_bindings") or []:
            r=db.scalar(select(DataCatalog).where(DataCatalog.kuscia_domaindata_id==b.get("domaindata_id"),DataCatalog.deleted_at.is_(None)))
            if r: inputs.append(r)
        for b in node.get("output_bindings") or []:
            dd=b.get("domaindata_id") or f"tds-{row.id[:8]}-{node['id']}-{b['port']}"[:63]
            existing=db.scalar(select(DataCatalog).where(DataCatalog.kuscia_domaindata_id==dd))
            if existing: continue
            conn=db.scalar(select(Connector).where(Connector.kuscia_domain_id==b.get("domain_id")))
            if not conn: continue
            resource=DataCatalog(name=b.get("name") or f"{project.name}-{node['id']}-{b['port']}",description="项目作业派生数据",
                tds_code=gen_data_code("resource", settings.tds_default_subject_code, settings.tds_default_region_industry),
                kind="resource",data_type=b.get("data_type","table"),provider_connector_id=conn.id,kuscia_domain_id=conn.kuscia_domain_id,
                kuscia_domaindata_id=dd,security_level=b.get("security_level","3"),columns=b.get("columns") or [],
                relative_uri=b.get("relative_uri") or f"projects/{project.id}/{row.id}/{node['id']}-{b['port']}.csv",
                datasource_id=b.get("datasource_id","default-data-source"),status="registered",created_by=row.created_by)
            db.add(resource); db.flush()
            audit_append(db,event_type="project.output.registered",stream_id=contract_stream(project.contract_id),resource_type="data_catalog",resource_id=resource.id,actor={"subject":row.created_by},payload={"contract_id":project.contract_id,"project_id":project.id,"run_id":row.id,"resource_id":resource.id,"tds_code":resource.tds_code,"kuscia_domaindata_id":dd,"workflow_node_id":node["id"],"output_port":b["port"]})
            for source in inputs: db.add(DataLineage(output_resource_id=resource.id,input_resource_id=source.id,project_id=project.id,
                project_run_id=row.id,workflow_node_id=node["id"],output_port=b["port"],app_image_name=node["app_image"]))
    db.commit()
