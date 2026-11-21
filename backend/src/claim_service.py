from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select
from .models import Machine,Claim,Inspection,Audit
from .health_models import ModelVersion,ClaimRoute

def obj(x):return {c.name:getattr(x,c.name) for c in x.__table__.columns}
def get(s,model,id):
    x=s.get(model,id)
    if not x:raise HTTPException(404,'记录不存在')
    return x
def audit(s,u,action,detail):s.add(Audit(actor=u['email'],action=action,detail=str(detail),at=datetime.now(timezone.utc).isoformat()))
def claim_view(s,c):
    d=obj(c);d['machine_serial']=s.get(Machine,c.machine_id).serial
    i=s.scalar(select(Inspection).where(Inspection.claim_id==c.id));d['inspection']=obj(i) if i else None
    r=s.scalar(select(ClaimRoute).where(ClaimRoute.claim_id==c.id))
    d['routing']=r.mode if r else None
    d['model_version']=s.get(ModelVersion,r.version_id).version_no if r and r.version_id else None
    return d
def submit(s,data,u):
    m=get(s,Machine,data.machine_id)
    if data.hours_at_failure<m.hours:raise HTTPException(409,'故障工时不能小于机具最新台账工时')
    # 受理与冻结/解冻共用版本行锁：同一时刻要么锁定活跃版本评分，要么转人工，原子切换只保留一套结果
    version=s.scalar(select(ModelVersion).where(ModelVersion.state=='active').with_for_update())
    if data.hours_at_failure>m.warranty_hours:status,note='out_of_warranty','超出质保工时'
    elif version is None:status,note='manual_review','分流模型版本已冻结，转人工受理'
    else:status,note='submitted',''
    c=Claim(**data.model_dump(),historical=False,status=status,assessment_note=note)
    m.hours=data.hours_at_failure;s.add(c);s.flush()
    if status=='manual_review':s.add(ClaimRoute(claim_id=c.id,version_id=None,mode='manual',note='版本冻结，转人工受理',created_at=datetime.now(timezone.utc).isoformat()))
    elif status=='submitted':s.add(ClaimRoute(claim_id=c.id,version_id=version.id,mode='model',created_at=datetime.now(timezone.utc).isoformat()))
    audit(s,u,'claim_received',c.code if status!='manual_review' else f'{c.code} / 版本冻结转人工');return claim_view(s,c)
def inspect(s,c,data,u):
    if c.status not in ['assessed','manual_review']:raise HTTPException(409,'仅完成风险分流或转人工受理的索赔可补拆检')
    i=s.scalar(select(Inspection).where(Inspection.claim_id==c.id))
    if not i:i=Inspection(claim_id=c.id,decision='pending',**data.model_dump());s.add(i)
    else:i.findings=data.findings;i.evidence_complete=data.evidence_complete
    audit(s,u,'inspection_updated',c.code);s.flush();return obj(i)
def adjudicate(s,c,decision,u):
    if c.status=='out_of_warranty':raise HTTPException(409,'机具故障工时已过保，不允许质保赔付')
    if c.status not in ['assessed','manual_review']:raise HTTPException(409,'索赔须完成风险分流或人工受理，且不可重复裁决')
    i=s.scalar(select(Inspection).where(Inspection.claim_id==c.id))
    if not i:raise HTTPException(409,'必须先记录拆检意见')
    if decision=='paid' and c.risk is not None and c.risk>=.5 and not i.evidence_complete:raise HTTPException(409,'高争议风险索赔必须补齐拆检证据后才能赔付')
    c.status=decision;i.decision=decision;audit(s,u,'claim_adjudicated',f'{c.code}:{decision}');return claim_view(s,c)
