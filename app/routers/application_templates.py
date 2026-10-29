"""Published application versions, project delegation and plan inspection."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import Connector, DigitalContract, Project, ConnectorCapability
from app.models.application_template import ApplicationTemplate, ApplicationTemplateVersion, ComputationDelegation, DelegationDecision, ExecutionIdentity
from app.services import application_template as svc, project as projects

router=APIRouter(tags=['application-framework'])
def wrap(data):return {'code':0,'message':'ok','data':data}
def operator(u):return 'operator' in u.get('roles',[])
def fail(message,code=409):raise HTTPException(code,message)
def call(fn):
    try:return fn()
    except (svc.TemplateError,projects.ProjectError) as e:fail(e.message,e.status_code)
def project(db,pid,u):return call(lambda:projects.get(db,pid,u['username'],operator(u)))
def author(row,u):
    if row.created_by!=u['username'] and not operator(u):fail('无权修改应用',403)
def business(db,p,u):
    if not any(c.created_by==u['username'] for c in projects.project_domains(db,p)):fail('仅业务参与方可操作',403)
def version_out(v):return {k:getattr(v,k) for k in ('id','application_id','version','definition','definition_hash','status','created_at')}
def template_out(db,r,u):
    versions=list(db.scalars(select(ApplicationTemplateVersion).where(ApplicationTemplateVersion.application_id==r.id).order_by(ApplicationTemplateVersion.version.desc())))
    return {'id':r.id,'name':r.name,'draft':r.draft if r.created_by==u['username'] or operator(u) else None,'created_by':r.created_by,'status':r.status,'versions':[version_out(v) for v in versions]}
class TemplateBody(BaseModel):
    name:str=Field(min_length=1,max_length=255)
    definition:dict=Field(default_factory=dict)
    draft:dict|None=None
class DelegationBody(BaseModel):
    instances:list[dict]=Field(default_factory=list)
    participants:list[dict]
    expires_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc)+timedelta(days=7))
class DecisionBody(BaseModel):
    connector_id:str
    decision:str

@router.get('/application-templates')
def listing(u=Depends(get_current_user),db:Session=Depends(get_db)):
    rows=list(db.scalars(select(ApplicationTemplate).order_by(ApplicationTemplate.created_at.desc())))
    return wrap([template_out(db,r,u) for r in rows if r.created_by==u['username'] or operator(u) or db.scalar(select(ApplicationTemplateVersion.id).where(ApplicationTemplateVersion.application_id==r.id))])
@router.post('/application-templates',status_code=201)
def create(body:TemplateBody,u=Depends(get_current_user),db:Session=Depends(get_db)):
    if not operator(u):fail('仅运营方可登记应用',403)
    r=ApplicationTemplate(name=body.name,draft=body.draft if body.draft is not None else body.definition,created_by=u['username']);db.add(r);db.commit();return wrap(template_out(db,r,u))
@router.get('/application-templates/versions/{vid}')
def get_version(vid:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    r=db.get(ApplicationTemplateVersion,vid)
    if not r or r.status!='published':fail('应用版本不存在',404)
    return wrap(version_out(r))
@router.get('/application-templates/{aid}')
def detail(aid:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    r=db.get(ApplicationTemplate,aid)
    if not r:fail('应用不存在',404)
    data=template_out(db,r,u)
    if not data['versions'] and data['draft'] is None:fail('应用不存在',404)
    return wrap(data)
@router.put('/application-templates/{aid}')
def update(aid:str,body:TemplateBody,u=Depends(get_current_user),db:Session=Depends(get_db)):
    r=db.get(ApplicationTemplate,aid)
    if not r:fail('应用不存在',404)
    author(r,u);r.name=body.name;r.draft=body.draft if body.draft is not None else body.definition;db.commit();return wrap(template_out(db,r,u))
@router.post('/application-templates/{aid}/publish')
def publish(aid:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    r=db.scalar(select(ApplicationTemplate).where(ApplicationTemplate.id==aid).with_for_update())
    if not r:fail('应用不存在',404)
    author(r,u);definition=call(lambda:svc.check_definition(db,r.draft,require_titles=True))
    n=(db.scalar(select(func.max(ApplicationTemplateVersion.version)).where(ApplicationTemplateVersion.application_id==aid)) or 0)+1
    v=ApplicationTemplateVersion(application_id=aid,version=n,definition=definition,definition_hash=svc.digest(definition));db.add(v);db.commit();return wrap(version_out(v))


def delegation_out(db,d,viewer_connector=None):
    scope=deepcopy(d.scope);p=db.get(Project,d.project_id)
    decisions=list(db.scalars(select(DelegationDecision).where(DelegationDecision.delegation_id==d.id)))
    participant=None
    for item in scope.get('participants',[]):
        c=db.get(Connector,item['connector_id']);caps=list(db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==c.id,ConnectorCapability.status=='verified')))
        network=next(((x.evidence or {}).get('network',{}) for x in caps if (x.evidence or {}).get('network')), {})
        item.update(connector_name=c.name,org_name=c.org_name,subject_id=(db.get(ExecutionIdentity,c.id).subject_id if db.get(ExecutionIdentity,c.id) else None),domain_id=network.get('execution_node_ref'))
        if c.id==viewer_connector:participant=item
    if viewer_connector:scope['participants']=[participant] if participant else []
    return {k:getattr(d,k) for k in ('id','project_id','version','status','scope_hash','contract_hash','expires_at','created_at')} | {'scope':scope,'project_name':p.name,'participant':participant,'decisions':[{'connector_id':x.connector_id,'kind':x.kind,'decision':x.decision,'decided_by':x.decided_by} for x in decisions if not viewer_connector or x.connector_id==viewer_connector]}
@router.get('/projects/{pid}/delegations')
def list_delegations(pid:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    p=project(db,pid,u);return wrap([delegation_out(db,d) for d in db.scalars(select(ComputationDelegation).where(ComputationDelegation.project_id==p.id).order_by(ComputationDelegation.version.desc()))])
@router.post('/projects/{pid}/delegations',status_code=201)
def create_delegation(pid:str,body:DelegationBody,u=Depends(get_current_user),db:Session=Depends(get_db)):
    p=project(db,pid,u);business(db,p,u);db.refresh(p,with_for_update=True)
    contract=db.get(DigitalContract,p.contract_id);ext=(contract.document.get('contractInfo',{}).get('expansionItem') or {}).get('computationOutsourcing',{})
    if ext.get('allowed') is not True:fail('合约扩展未允许外包计算',403)
    if svc.utc(body.expires_at)<=datetime.now(timezone.utc):fail('委托有效期必须在未来',422)
    if svc.utc(body.expires_at)>datetime.now(timezone.utc)+timedelta(days=366):fail('委托有效期过长',422)
    if not body.participants:fail('需要计算服务席位',422)
    project_seats=not body.instances
    for x in body.instances:
        if set(x)!={'id','version_id'} or not isinstance(x['id'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,19}',x['id']) or not isinstance(x['version_id'],str):fail('实例须包含合法 id 和 version_id',422)
    if len({x['id'] for x in body.instances})!=len(body.instances):fail('实例 id 不能重复',422)
    for x in body.participants:
        if set(x)!={'connector_id','roles'} or not isinstance(x['connector_id'],str) or not isinstance(x['roles'],list) or not all(isinstance(r,str) and r for r in x['roles']):fail('计算参与方须包含 connector_id 和角色列表',422)
        if len(set(x['roles']))!=len(x['roles']):fail('计算职责不能重复',422)
    ids=[x.get('connector_id') for x in body.participants]
    if len(set(ids))!=len(ids):fail('计算连接器不能重复',422)
    wanted=set()
    for instance in body.instances:
        v=db.get(ApplicationTemplateVersion,instance.get('version_id'))
        if not v or v.status!='published':fail('应用版本不存在',422)
        if v.definition.get('architecture')!='outsourced':fail('计算委托只能用于外包应用',422)
        wanted.update(r['name'] for r in v.definition['roles'] if r.get('source','').startswith('delegate:'))
    business_ids={x.id for x in projects.project_domains(db,p)}
    for item in body.participants:
        c=db.get(Connector,item.get('connector_id'))
        if not c or c.status!='active' or c.deleted_at or c.id in business_ids:fail('计算服务连接器未激活或不是独立参与方',422)
        if not project_seats and (not item.get('roles') or not set(item['roles'])<=wanted):fail('计算职责不在应用声明范围',422)
        allowed=ext.get('allowedConnectors')
        if allowed and c.id not in allowed and c.tds_code not in allowed:fail('计算服务不在合约许可范围',403)
    assigned=[r for x in body.participants for r in x['roles']]
    if not project_seats and (set(assigned)!=wanted or len(assigned)!=len(set(assigned))):fail('计算职责必须完整且唯一覆盖',422)
    subjects=call(lambda:[svc.subject(db,c) for c in ids])
    if len(set(subjects))!=len(ids):fail('计算参与方必须属于独立主体',422)
    for old in db.scalars(select(ComputationDelegation).where(ComputationDelegation.project_id==pid,ComputationDelegation.status.in_(['pending','active']))):old.status='superseded'
    scope={'mode':'project-seats' if project_seats else 'application-instances','instances':[{'id':x['id'],'version_id':x['version_id']} for x in body.instances],'participants':[{'connector_id':x['connector_id'],'roles':([f'seat:{i}'] if project_seats else x['roles'])} for i,x in enumerate(body.participants)]}
    n=(db.scalar(select(func.max(ComputationDelegation.version)).where(ComputationDelegation.project_id==pid)) or 0)+1
    d=ComputationDelegation(project_id=pid,version=n,scope=scope,scope_hash=svc.digest(scope),contract_hash=contract.document_hash,expires_at=body.expires_at,created_by=u['username']);db.add(d);db.flush()
    # Record platform confirmation for every business party and service seat.
    # Job approval remains the human review boundary.
    d.status='active'
    for c in projects.project_domains(db,p):
        db.add(DelegationDecision(delegation_id=d.id,connector_id=c.id,kind='business',decision='accepted',decided_by='system'))
    for item in scope['participants']:
        db.add(DelegationDecision(delegation_id=d.id,connector_id=item['connector_id'],kind='service',decision='accepted',decided_by='system'))
    db.commit();return wrap(delegation_out(db,d))
@router.get('/computation-delegations/inbox')
def inbox(connector_id:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    c=db.get(Connector,connector_id)
    if not c or c.created_by!=u['username']:fail('无权查看其他连接器委托',403)
    rows=[d for d in db.scalars(select(ComputationDelegation).order_by(ComputationDelegation.created_at.desc())) if any(x['connector_id']==c.id for x in d.scope.get('participants',[]))]
    return wrap([delegation_out(db,d,c.id) for d in rows])
@router.post('/computation-delegations/{did}/decision')
def decide(did:str,body:DecisionBody,u=Depends(get_current_user),db:Session=Depends(get_db)):
    d=db.scalar(select(ComputationDelegation).where(ComputationDelegation.id==did).with_for_update())
    if not d:fail('委托不存在',404)
    if body.decision not in ('accepted','rejected'):fail('决定仅支持 accepted/rejected',422)
    c=db.get(Connector,body.connector_id)
    if not c or c.created_by!=u['username']:fail('只能代表自己的连接器确认',403)
    p=db.get(Project,d.project_id);business_ids={x.id for x in projects.project_domains(db,p)};service_ids={x['connector_id'] for x in d.scope['participants']}
    if c.id not in business_ids|service_ids:fail('连接器不在委托范围内',403)
    kind='business' if c.id in business_ids else 'service'
    row=db.scalar(select(DelegationDecision).where(DelegationDecision.delegation_id==did,DelegationDecision.connector_id==c.id,DelegationDecision.kind==kind))
    if row and row.decision==body.decision and ((d.status=='active' and body.decision=='accepted') or (d.status=='rejected' and body.decision=='rejected')) and svc.utc(d.expires_at)>datetime.now(timezone.utc):
        return wrap(delegation_out(db,d,c.id if kind=='service' else None))
    if d.status!='pending' or svc.utc(d.expires_at)<=datetime.now(timezone.utc):fail('委托已终结或过期')
    if row:
        if row.decision!=body.decision:fail('已确认的决定不可覆盖')
    else:db.add(DelegationDecision(delegation_id=did,connector_id=c.id,kind=kind,decision=body.decision,decided_by=u['username']))
    db.flush();accepted={x.connector_id for x in db.scalars(select(DelegationDecision).where(DelegationDecision.delegation_id==did,DelegationDecision.decision=='accepted'))}
    if body.decision=='rejected':d.status='rejected'
    elif accepted>=business_ids|service_ids:d.status='active'
    db.commit();return wrap(delegation_out(db,d,c.id if kind=='service' else None))
@router.post('/projects/{pid}/delegations/{did}/revoke')
def revoke(pid:str,did:str,u=Depends(get_current_user),db:Session=Depends(get_db)):
    p=project(db,pid,u);business(db,p,u);d=db.get(ComputationDelegation,did)
    if not d or d.project_id!=pid:fail('委托不存在',404)
    d.status='revoked';db.commit();return wrap(delegation_out(db,d))

@router.post('/projects/{pid}/delegation-readiness')
def delegation_readiness(pid:str,body:dict,u=Depends(get_current_user),db:Session=Depends(get_db)):
    p=project(db,pid,u)
    return wrap(call(lambda:svc.delegation_readiness(db,p,body.get('workflow',{}))))

@router.post('/projects/{pid}/execution-plan')
def execution_plan(pid:str,body:dict,u=Depends(get_current_user),db:Session=Depends(get_db)):
    p=project(db,pid,u)
    w=call(lambda:svc.expand(db,p,body.get('workflow',{})));call(lambda:projects.validate_workflow(db,p,w))
    participants=[]
    for cid in dict.fromkeys(x['domain_id'] for n in w['nodes'] for x in n['parties']):
        c=db.get(Connector,cid);caps=list(db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==cid,ConnectorCapability.status=='verified')))
        network=next(((cap.evidence or {}).get('network',{}) for cap in caps if (cap.evidence or {}).get('network')), {})
        participants.append({'connector_id':cid,'connector_name':c.name,'subject_id':(db.get(ExecutionIdentity,c.id).subject_id if db.get(ExecutionIdentity,c.id) else None),'domain_id':network.get('execution_node_ref'),'cluster':'configured-master'})
    return wrap({'workflow':w,'participants':participants,'applications':w.get('application_versions',{}),'hash':svc.digest(w)})

class ExecutionIdentityBody(BaseModel):
    subject_id:str=Field(min_length=1,max_length=128)
    status:str='verified'

@router.get('/computation-services')
def computation_services(u=Depends(get_current_user),db:Session=Depends(get_db)):
    """Minimal invitation directory; connector ownership details stay private."""
    rows=[]
    for c in db.scalars(select(Connector).where(Connector.status=='active',Connector.deleted_at.is_(None)).order_by(Connector.name)):
        identity=db.get(ExecutionIdentity,c.id)
        if not identity or identity.status!='verified':continue
        caps=db.scalars(select(ConnectorCapability).where(ConnectorCapability.connector_id==c.id,ConnectorCapability.status=='verified'))
        if not any((cap.evidence or {}).get('network',{}).get('execution_node_ref') and (not cap.expires_at or svc.utc(cap.expires_at)>datetime.now(timezone.utc)) for cap in caps):continue
        rows.append({'id':c.id,'name':c.name,'org_name':c.org_name,'status':c.status,'subject_id':identity.subject_id})
    return wrap(rows)

@router.get('/execution-identities')
def execution_identities(u=Depends(get_current_user),db:Session=Depends(get_db)):
    rows=list(db.scalars(select(ExecutionIdentity)))
    return wrap([{'connector_id':x.connector_id,'subject_id':x.subject_id,'status':x.status,'verified_by':x.verified_by,'updated_at':x.updated_at} for x in rows])

@router.put('/execution-identities/{cid}')
def set_execution_identity(cid:str,body:ExecutionIdentityBody,u=Depends(get_current_user),db:Session=Depends(get_db)):
    if not operator(u):fail('仅运营方可以核验执行主体身份',403)
    if not db.get(Connector,cid):fail('连接器不存在',404)
    if body.status not in {'verified','revoked'}:fail('身份状态无效',422)
    row=db.get(ExecutionIdentity,cid)
    if not row:row=ExecutionIdentity(connector_id=cid,subject_id=body.subject_id,status=body.status,verified_by=u['username']);db.add(row)
    else:row.subject_id=body.subject_id;row.status=body.status;row.verified_by=u['username']
    # Identity changes invalidate prior delegations rather than silently reinterpreting them.
    for d in db.scalars(select(ComputationDelegation).where(ComputationDelegation.status.in_(['pending','active']))):
        if any(p['connector_id']==cid for p in d.scope.get('participants',[])):d.status='identity-changed'
    db.commit();return wrap({'connector_id':cid,'subject_id':row.subject_id,'status':row.status})
