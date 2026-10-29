"""Declarative application compilation; no engine calls or application-specific branches."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib, json, re
from functools import wraps
from types import SimpleNamespace
from sqlalchemy import select
from app.models import AppImage, Connector, DigitalContract
from app.models.application_template import ApplicationTemplateVersion, ComputationDelegation, DelegationDecision, ExecutionIdentity

class TemplateError(ValueError):
    def __init__(self,message,status_code=422): super().__init__(message); self.message=message; self.status_code=status_code

def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def require(condition,message,code=422):
    if not condition: raise TemplateError(message,code)
def subject(db,connector_id):
    row=db.get(ExecutionIdentity,connector_id)
    require(row and row.status=='verified','参与方缺少运营方核验的主体身份',409)
    return row.subject_id

def utc(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def declarative_input(fn):
    @wraps(fn)
    def checked(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except TemplateError:raise
        except (KeyError,TypeError,AttributeError,ValueError,IndexError) as exc:
            raise TemplateError('应用定义或实例字段结构无效，请检查角色、参数和端口映射') from exc
    return checked

def validate_value(value,schema,path='参数'):
    kind=schema.get('type')
    tests={'string':lambda:isinstance(value,str),'integer':lambda:isinstance(value,int) and not isinstance(value,bool),'number':lambda:isinstance(value,(int,float)) and not isinstance(value,bool),'boolean':lambda:isinstance(value,bool),'array':lambda:isinstance(value,list),'object':lambda:isinstance(value,dict)}
    if kind: require(kind in tests and tests[kind](),f'{path} 类型应为 {kind}')
    if 'enum' in schema: require(value in schema['enum'],f'{path} 不在允许选项内')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if 'minimum' in schema: require(value>=schema['minimum'],f'{path} 小于最小值')
        if 'maximum' in schema: require(value<=schema['maximum'],f'{path} 大于最大值')
    if isinstance(value,str):
        if 'minLength' in schema: require(len(value)>=schema['minLength'],f'{path} 太短')
        if 'maxLength' in schema: require(len(value)<=schema['maxLength'],f'{path} 太长')
    if kind=='array':
        if 'minItems' in schema: require(len(value)>=schema['minItems'],f'{path} 元素过少')
        if 'maxItems' in schema: require(len(value)<=schema['maxItems'],f'{path} 元素过多')
        for i,v in enumerate(value): validate_value(v,schema.get('items',{}),f'{path}[{i}]')
    if kind=='object':
        props=schema.get('properties',{})
        for name in schema.get('required',[]): require(name in value,f'{path} 缺少 {name}')
        for name,v in value.items():
            require(name in props or schema.get('additionalProperties') is True,f'{path} 包含未声明字段 {name}')
            if name in props: validate_value(v,props[name],path+'.'+name)

def parameters(schema,provided):
    require(isinstance(provided,dict),'参数须为对象')
    values={k:deepcopy(v['default']) for k,v in schema.get('properties',{}).items() if 'default' in v}
    values.update(provided); validate_value(values,{**schema,'type':'object'},'应用参数'); return values

def image_snapshot(app):
    keys=('id','name','display_name','description','capability','operations','uc_capabilities','registry_source','registry','image_name','image_tag','deploy_templates','config_templates','job_template','io_schema','party_schema','parameter_schema','ui_schema','task_input_template','scope','status')
    return {k:deepcopy(getattr(app,k,None)) for k in keys}

def output_path(template,project_id,run_id,task_id,port):
    """Render a single declared output file inside its execution workspace."""
    require(isinstance(template,str) and bool(template),'输出路径模板须为字符串')
    context={'project.id':project_id,'run.id':run_id,'task.id':task_id}
    for value in context.values():
        require(isinstance(value,str) and value and value not in {'.','..'} and '/' not in value and '\\' not in value and not any(ord(c)<32 for c in value),'输出路径变量必须为单段标识')
    def replace(match):
        key=match.group(1).strip();require(key in context,'输出路径模板引用未知变量');return context[key]
    rendered=re.sub(r'\{\{\s*([^{}]+?)\s*\}\}',replace,template)
    require(not any(c in rendered for c in ('{','}','\\')) and not any(ord(c)<32 for c in rendered),'输出路径模板包含非法字符')
    parts=rendered.split('/')
    require(all(p and p not in {'.','..'} for p in parts) and rendered.startswith(f'projects/{project_id}/{run_id}/'),'输出路径必须位于本次项目执行工作区')
    return rendered

@declarative_input
def check_definition(db,definition,require_titles=False):
    require(isinstance(definition,dict),'应用定义须为对象')
    d=deepcopy(definition); require(d.get('architecture') in ('cs','outsourced'),'需要声明 cs 或 outsourced 计算架构')
    tasks=d.get('tasks',[]); require(isinstance(tasks,list) and 0<len(tasks)<=128,'应用需要 1–128 个任务')
    ids=[x.get('id') for x in tasks]; require(len(ids)==len(set(ids)) and all(isinstance(x,str) and re.fullmatch('[a-z][a-z0-9-]{0,23}',x) for x in ids),'任务标识须唯一且符合短 RFC1123 名称')
    roles=d.get('roles',[]); names=[r.get('name') for r in roles]
    require(names and len(names)==len(set(names)) and all(isinstance(n,str) and n for n in names),'应用角色须非空且唯一')
    if require_titles:
        for r in roles:require(isinstance(r.get('title'),str) and bool(r['title'].strip()),'请补充应用角色可读名称: '+r['name'])
        for direction in ('inputs','outputs'):
            for port in d.get(direction,[]):require(isinstance(port.get('title'),str) and bool(port['title'].strip()),'请补充公开端口可读名称: '+str(port.get('name','')))
    rules={r['name']:r for r in roles}
    def role_source(name,seen):
        require(name not in seen,'角色预填规则存在循环');r=rules[name];s=r.get('source','manual')
        require(s in ('provider','consumer','initiator','manual') or re.fullmatch(r'delegate:[0-9]+',s) or s.startswith('same:'),'未知角色预填来源')
        if s.startswith('same:'):
            other=s[5:];require(other in rules,'同角色预填引用不存在');role_source(other,seen|{name})
    for name in names: role_source(name,set())
    if d['architecture']=='cs': require(not any(r.get('source','').startswith('delegate:') for r in roles),'CS 应用不能声明外包席位')
    for group in d.get('distinct_roles',[]): require(len(group)>1 and set(group)<=set(names),'独立性约束引用未知角色')
    schema=d.get('parameter_schema',{'type':'object','properties':{}});require(schema.get('type','object')=='object','应用参数 schema 须为 object')
    props=schema.get('properties',{}); snapshots={}
    require(isinstance(props,dict),'应用参数 properties 须为对象')
    require(set(schema.get('required',[]))<=set(props),'必填参数未在 properties 声明')
    for name,spec in props.items():
        require(isinstance(spec,dict),'参数 schema 须为对象')
        if 'default' in spec:validate_value(spec['default'],spec,name)
    for t in tasks:
        app=db.scalar(select(AppImage).where(AppImage.name==t.get('app_image'),AppImage.status=='registered'))
        require(app is not None,f"任务 {t['id']} 的 AppImage 不存在或已下架")
        require(app.task_input_template is not None,'AppImage 缺少 task_input_template')
        architectures=(app.party_schema or {}).get('architectures',['cs'])
        require(d['architecture'] in architectures,'AppImage '+app.name+' 未声明支持 '+d['architecture']+' 架构')
        snapshots[app.name]=image_snapshot(app)
        for output in (app.io_schema or {}).get('outputs',[]):
            if 'path_template' in output:output_path(output['path_template'],'project','run','task',str(output.get('name') or ''))
        supported={x.get('role','') for x in app.deploy_templates or []};require(t.get('roles') and set(t['roles'])<=supported,f"任务 {t['id']} 使用未声明 AppImage 角色")
        require(set(t['roles'].values())<=set(names),'任务引用未知应用角色')
        target_schema=app.parameter_schema or {}; targets=target_schema.get('properties',{})
        for name,binding in t.get('parameters',{}).items():
            require(name in targets,'任务参数未在 AppImage 声明: '+name)
            require(isinstance(binding,dict) and set(binding) in ({'parameter'},{'value'}),'参数映射只允许 parameter 或 value')
            if 'parameter' in binding:
                require(binding['parameter'] in props,'映射引用未知应用参数')
                src=props[binding['parameter']];dst=targets[name]
                require(not src.get('type') or not dst.get('type') or src['type']==dst['type'],'应用与任务参数类型不兼容')
            else: validate_value(binding['value'],targets[name],name)
        require(set(target_schema.get('required',[]))<=set(t.get('parameters',{})),'缺少任务必填参数映射')
    by_id={t['id']:t for t in tasks}
    def port(task,name,direction):
        require(task in by_id,'端口引用未知任务')
        ports={p['name']:p for p in (snapshots[by_id[task]['app_image']].get('io_schema') or {}).get(direction,[])}
        require(name in ports,f'{task} 未声明{direction}端口 {name}');return ports[name]
    seen_inputs=set(); public_names=set()
    for p in d.get('inputs',[]):
        require(p.get('name') and p['name'] not in public_names and p.get('role') in names,'公开输入名称重复或角色未知');public_names.add(p['name'])
        require(p.get('targets'),'公开输入缺少内部映射')
        for target in p['targets']:
            key=(target.get('task'),target.get('port')); require(key not in seen_inputs,'内部输入存在多个来源');seen_inputs.add(key)
            target_port=port(*key,'inputs');task=by_id[key[0]]
            require(not target_port.get('role') or task['roles'].get(target_port['role'])==p['role'],'公开输入所属角色与内部端口不一致')
    public_names=set()
    for p in d.get('outputs',[]):
        require(p.get('name') and p['name'] not in public_names,'公开输出名称重复');public_names.add(p['name']);target=port(p.get('task'),p.get('port'),'outputs')
        owner=by_id[p['task']]['roles'].get(target.get('role'))
        if p.get('role'):require(p['role'] in names and (not owner or p['role']==owner),'公开输出所属角色与内部端口不一致')
        elif owner:p['role']=owner
    graph={i:[] for i in ids}
    for e in d.get('edges',[]):
        require(e.get('source') in graph and e.get('target') in graph,'依赖引用未知任务');require(e.get('type','control') in ('control','data'),'依赖类型无效')
        graph[e['source']].append(e['target'])
        if e.get('type')=='data':
            key=(e['target'],e.get('target_handle'));require(key not in seen_inputs,'内部输入存在多个来源');seen_inputs.add(key)
            a=port(e['source'],e.get('source_handle'),'outputs');b=port(*key,'inputs')
            require(a.get('kind')==b.get('kind'),'数据端口形态不兼容')
            if a.get('formats') and b.get('formats'): require(bool(set(a['formats'])&set(b['formats'])),'数据端口格式不兼容')
    active=set();done=set()
    def walk(n):
        require(n not in active,'任务依赖不能包含环')
        if n in done:return
        active.add(n)
        for x in graph[n]:walk(x)
        active.remove(n);done.add(n)
    for n in ids:walk(n)
    for t in tasks:
        for p in (snapshots[t['app_image']].get('io_schema') or {}).get('inputs',[]):
            require(not p.get('required',True) or (t['id'],p['name']) in seen_inputs,'必填内部输入缺少来源: '+t['id']+'.'+p['name'])
    d['appimage_snapshots']=snapshots
    return d

def delegation_effective(db,d,contract):
    return d.status=='active' and utc(d.expires_at)>datetime.now(timezone.utc) and d.contract_hash==contract.document_hash

def approved_services(db,project):
    contract=db.get(DigitalContract,project.contract_id)
    if not contract or ((contract.document.get('contractInfo') or {}).get('expansionItem') or {}).get('computationOutsourcing',{}).get('allowed') is not True:return None
    rows=db.scalars(select(ComputationDelegation).where(ComputationDelegation.project_id==project.id).order_by(ComputationDelegation.version.desc()))
    for d in rows:
        if delegation_effective(db,d,contract):return d
    return None


def resolve_instance_roles(db,project,inst,version):
    from app.services.project import contract_input_scope
    provider,consumer,_=contract_input_scope(db,project)
    business={provider,consumer};contract=db.get(DigitalContract,project.contract_id);delegation=approved_services(db,project)
    d=version.definition;iid=inst['id']
    rules={r['name']:r for r in d['roles']};explicit=inst.get('roles',{});resolved={};visiting=set()
    require(set(explicit)<=set(rules),'实例绑定未知角色')
    participants=[]
    if d['architecture']=='outsourced':
        ext=(contract.document.get('contractInfo',{}).get('expansionItem') or {}).get('computationOutsourcing',{})
        require(ext.get('allowed') is True,'合约扩展未允许外包计算',403)
        require(delegation is not None,'项目计算委托尚未生效',409)
        if delegation.scope.get('mode')!='project-seats':
            require({'id':iid,'version_id':version.id} in delegation.scope.get('instances',[]),'该应用实例不在计算委托范围内',403)
        participants=delegation.scope.get('participants',[])
    def resolve(role):
        if role in resolved:return resolved[role]
        require(role not in visiting,'角色预填存在循环');visiting.add(role);r=rules[role];source=r.get('source','manual');value=None
        if source=='provider':value=provider
        elif source=='consumer':value=consumer
        elif source=='initiator':value=project.initiator_connector_id
        elif source.startswith('same:'):value=resolve(source[5:])
        elif source.startswith('delegate:'):
            index=int(source.split(':')[1]);require(index<len(participants),'应用需要更多计算席位，请补充计算委托',409);value=participants[index]['connector_id']
        given=explicit.get(role)
        require(not r.get('locked',True) or not given or not value or given==value,'不能修改锁定的角色预填: '+role,403)
        value=given or value;require(value,'缺少角色绑定: '+role)
        allowed=business|{p['connector_id'] for p in participants if role in p.get('roles',[]) or delegation.scope.get('mode')=='project-seats'}
        require(value in allowed,'角色未取得项目授权: '+role,403)
        connector=db.get(Connector,value);require(connector and connector.status=='active' and not connector.deleted_at,'参与连接器未激活',409)
        visiting.remove(role);resolved[role]=value;return value
    for role in rules:resolve(role)
    for group in d.get('distinct_roles',[]):
        conns=[db.get(Connector,resolved[r]) for r in group]
        require(len({x.id for x in conns})==len(group) and len({subject(db,x.id) for x in conns})==len(group),'计算角色必须属于不同主体和连接器',403)
    return resolved

@declarative_input
def expand(db,project,workflow):
    from app.services.project import contract_input_scope
    require(isinstance(workflow,dict),'工作流须为对象')
    detached = workflow.get('detached_applications', [])
    require(isinstance(detached,list),'解除组合的应用来源须为数组')
    detached_ids=set()
    detached_versions={}
    for origin in detached:
        require(isinstance(origin,dict) and origin.get('id') not in detached_ids,'解除组合来源实例重复')
        iid=origin.get('id');detached_ids.add(iid)
        # Re-enter the same published-version, contract-extension, delegation,
        # role prefill and distinct-subject checks as an ordinary application.
        proof_origin=deepcopy(origin)
        version=db.get(ApplicationTemplateVersion,origin.get('version_id'))
        require(version and version.status=='published','应用版本不存在或已停用',409)
        # Public inputs supplied by another group need not exist in origin.inputs.
        # Fill proof-only bindings from submitted task roles, then independently
        # validate those roles against authoritative prefill/delegation below.
        proof_origin.setdefault('inputs',{})
        for port in version.definition.get('inputs',[]):
            if port['name'] in proof_origin['inputs']:continue
            target=port['targets'][0]
            task=next(t for t in version.definition['tasks'] if t['id']==target['task'])
            app_role=next((ar for ar,rr in task['roles'].items() if rr==port['role']),None)
            submitted=next((n for n in workflow.get('nodes',[]) if n.get('application_instance')==iid and n.get('template_task')==target['task']),{})
            domain=next((p.get('domain_id') for p in submitted.get('parties',[]) if p.get('role')==app_role),None)
            proof_origin['inputs'][port['name']]={'domain_id':domain}
        baseline=expand(db,project,{'applications':[proof_origin],'nodes':[],'edges':[]})
        expected={n['template_task']:n for n in baseline['nodes']}
        actual=[n for n in workflow.get('nodes',[]) if n.get('application_instance')==iid]
        require(len(actual)==len(expected) and {n.get('template_task') for n in actual}==set(expected),'解除组合任务必须完整保留且不得重复',403)
        for n in actual:
            original=expected[n['template_task']]
            require(n.get('detached') is True and n.get('template_version')==origin.get('version_id') and n.get('app_image')==original['app_image'] and n.get('id')==original['id'],'解除组合任务的镜像来源不可修改',403)
            parties=lambda value:sorted((p.get('role'),p.get('domain_id')) for p in value or [])
            require(parties(n.get('parties'))==parties(original['parties']),'解除组合不能修改已授权角色和参与方',403)
        detached_versions.update(baseline.get('application_versions',{}))
    require(all(not n.get('template_version') or (n.get('detached') is True and n.get('application_instance') in detached_ids) for n in workflow.get('nodes',[])),'展开任务须携带有效解除组合来源')
    w=deepcopy(workflow);instances=w.get('applications',[])
    require(isinstance(instances,list),'应用实例须为数组')
    if not instances:
        snapshots={}
        for n in w.get('nodes',[]):
            if not n.get('template_version'):continue
            fingerprint=digest(vars(snapshot_app(db,n)))
            require(n['app_image'] not in snapshots or snapshots[n['app_image']]==fingerprint,'同一工作流引用了同名但不同定义的组件版本，请登记不同 AppImage 名称')
            snapshots[n['app_image']]=fingerprint
        w['application_versions']=detached_versions
        return w
    provider,consumer,_=contract_input_scope(db,project)
    business={provider,consumer}; contract=db.get(DigitalContract,project.contract_id);delegation=approved_services(db,project)
    nodes=list(w.get('nodes',[]));edges=list(w.get('edges',[]));instance_ids=set(detached_ids);published=dict(detached_versions)
    for inst in instances:
        iid=inst.get('id');require(isinstance(iid,str) and re.fullmatch('[a-z][a-z0-9-]{0,19}',iid) and iid not in instance_ids,'实例标识须唯一、短 RFC1123 名称');instance_ids.add(iid)
        require(isinstance(inst.get('version_id'),str) and bool(inst['version_id']),'应用版本标识须为字符串')
        version=db.get(ApplicationTemplateVersion,inst.get('version_id'));require(version and version.status=='published','应用版本不存在或已停用',409)
        d=version.definition;published[iid]={'version_id':version.id,'version':version.version,'hash':version.definition_hash}
        resolved=resolve_instance_roles(db,project,inst,version)
        values=parameters(d.get('parameter_schema',{}),inst.get('parameters',{}))
        by_task={}
        for t in d['tasks']:
            tid=iid+'-'+t['id'];require(len(tid)<=40,'展开任务标识超过长度限制')
            params={k:deepcopy(values[v['parameter']] if 'parameter' in v else v['value']) for k,v in t.get('parameters',{}).items() if 'parameter' not in v or v['parameter'] in values}
            snap=d['appimage_snapshots'][t['app_image']];validate_value(params,{**(snap.get('parameter_schema') or {}),'type':'object'},'任务参数')
            n={'id':tid,'app_image':t['app_image'],'parameters':params,'parties':[{'role':ar,'domain_id':resolved[rr]} for ar,rr in t['roles'].items()], 'input_bindings':[], 'output_bindings':[], 'template_version':version.id,'template_task':t['id'],'application_instance':iid}
            by_task[t['id']]=n;nodes.append(n)
        for p in d.get('inputs',[]):
            binding=inst.get('inputs',{}).get(p['name'])
            incoming=any(e.get('type')=='data' and e.get('target')==iid and e.get('target_handle')==p['name'] for e in workflow.get('edges',[]))
            require(not (binding and incoming),'公开输入存在多个来源: '+p['name'])
            if incoming:continue
            require(binding is not None,'缺少应用输入: '+p['name'])
            require(binding.get('domain_id')==resolved[p['role']],'应用输入所属参与方不匹配',403)
            for target in p['targets']:by_task[target['task']]['input_bindings'].append({**binding,'port':target['port']})
        for t in d['tasks']:
            n=by_task[t['id']];snap=d['appimage_snapshots'][t['app_image']]
            for port in (snap.get('io_schema') or {}).get('outputs',[]):
                role=port.get('role');require(role in t['roles'],'输出端口必须声明所属角色')
                n['output_bindings'].append({'port':port['name'],'domain_id':resolved[t['roles'][role]]})
        for e in d.get('edges',[]):edges.append({**e,'source':by_task[e['source']]['id'],'target':by_task[e['target']]['id']})
    # Detached groups use task handles directly; only intact instances translate.
    instance_ids={inst['id'] for inst in instances}
    # Resolve public handles; control edges connect every terminal/root task.
    translated=[]
    for original in edges:
        variants=[dict(original)]
        for side,direction in (('source','outputs'),('target','inputs')):
            mapped=[]
            for e in variants:
                if e.get(side) not in instance_ids:
                    mapped.append(e);continue
                inst=next(i for i in instances if i['id']==e[side]);d=db.get(ApplicationTemplateVersion,inst['version_id']).definition
                key='source_handle' if side=='source' else 'target_handle'
                if e.get('type','control')=='control':
                    excluded={x['source' if side=='source' else 'target'] for x in d.get('edges',[])}
                    targets=[{'task':t['id']} for t in d['tasks'] if t['id'] not in excluded]
                else:
                    p=next((p for p in d.get(direction,[]) if p['name']==e.get(key)),None)
                    require(p,'外围连线引用未知应用端口')
                    targets=[{'task':p['task'],'port':p['port']}] if side=='source' else p['targets']
                for target in targets:
                    item={**e,side:inst['id']+'-'+target['task']}
                    if 'port' in target:item[key]=target['port']
                    mapped.append(item)
            variants=mapped
        translated.extend(variants)
    edges=translated
    snapshots={}
    for n in nodes:
        if not n.get('template_version'):continue
        app=snapshot_app(db,n);fingerprint=digest(vars(app))
        require(n['app_image'] not in snapshots or snapshots[n['app_image']]==fingerprint,'同一工作流引用了同名但不同定义的组件版本，请登记不同 AppImage 名称')
        snapshots[n['app_image']]=fingerprint
    w.update(nodes=nodes,edges=edges,application_versions=published)
    return w

def snapshot_app(db,node):
    if not node.get('template_version'):return db.scalar(select(AppImage).where(AppImage.name==node.get('app_image'),AppImage.status=='registered'))
    version=db.get(ApplicationTemplateVersion,node['template_version']);require(version and version.status=='published','模板版本不可用',409)
    task=next((t for t in version.definition['tasks'] if t['id']==node.get('template_task')),None)
    require(task and task['app_image']==node.get('app_image'),'模板任务来源不匹配',403)
    return SimpleNamespace(**version.definition['appimage_snapshots'][task['app_image']])

@declarative_input
def delegation_readiness(db,project,workflow):
    """Check authorization before resource selection or connectivity; same role rules as compilation."""
    from app.models import ConnectorCapability
    from app.services.project import _resolve_application_contract, ProjectError
    instances=workflow.get('applications',[])+workflow.get('detached_applications',[])
    required=False;issues=[];roles={}
    for inst in instances:
        version=db.get(ApplicationTemplateVersion,inst.get('version_id'))
        require(version and version.status=='published','应用版本不存在',409)
        d=version.definition
        required=required or d['architecture']=='outsourced'
        try:
            resolved=resolve_instance_roles(db,project,inst,version);roles[inst['id']]=resolved
            for task in d['tasks']:
                app=SimpleNamespace(**d['appimage_snapshots'][task['app_image']])
                requirements=_resolve_application_contract(db,db.get(DigitalContract,project.contract_id),app)[3]
                for cid in set(resolved[r] for r in task['roles'].values()):
                    caps=list(db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==cid,ConnectorCapability.status=='verified')))
                    valid={c.capability_code for c in caps if not c.expires_at or utc(c.expires_at)>datetime.now(timezone.utc)}
                    missing=set(requirements)-valid
                    require(not missing,'连接器 '+db.get(Connector,cid).name+' 缺少应用能力: '+', '.join(sorted(missing)),409)
        except (TemplateError,ProjectError) as e:issues.append({'instance_id':inst['id'],'message':e.message})
    return {'required':required,'ready':not issues,'issues':issues,'roles':roles}
