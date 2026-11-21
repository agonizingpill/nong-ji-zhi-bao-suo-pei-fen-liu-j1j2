import json
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select,func
from .database import Session
from .models import Claim
from .health_models import ModelVersion,HealthWindow,HealthSample,ClaimRoute
from .claim_service import obj,audit

MIN_PART_SAMPLE=8
MAX_CALIBRATION_ERROR=.2
WARN_CALIBRATION_ERROR=.15
PARTS=['hydraulic','engine','transmission']
BATCH=50

def now():return datetime.now(timezone.utc).isoformat()
def active_version(s):return s.scalar(select(ModelVersion).where(ModelVersion.state=='active').with_for_update())
def window_for(s,version):
    w=s.scalar(select(HealthWindow).where(HealthWindow.version_id==version.id))
    if not w:w=HealthWindow(version_id=version.id,state='open');s.add(w);s.flush()
    return w
def eligible_stmt():
    # 只纳入标签齐全的结案索赔：已结案、争议标签与模型评分齐全、受理时按模型路由、尚未进入任何窗口
    return select(Claim).join(ClaimRoute,ClaimRoute.claim_id==Claim.id).where(
        Claim.status.in_(['paid','denied']),Claim.disputed.isnot(None),Claim.risk.isnot(None),
        ClaimRoute.mode=='model',~select(HealthSample.id).where(HealthSample.claim_id==Claim.id).exists())
def pending_count(s):return s.scalar(select(func.count()).select_from(eligible_stmt().subquery()))
def pending_exists():
    with Session() as s:return s.scalar(eligible_stmt().limit(1)) is not None

def collect_batch(s,window):
    rows=s.scalars(eligible_stmt().order_by(Claim.id).limit(BATCH)).all()
    for c in rows:s.add(HealthSample(window_id=window.id,claim_id=c.id,part=c.part,predicted=c.risk,label=c.disputed))
    s.flush();return len(rows)

def part_stats(samples):
    by={p:[] for p in PARTS}
    for x in samples:
        if x.part in by:by[x.part].append(x)
    out=[]
    for part in PARTS:
        xs=by[part];n=len(xs)
        mean_p=round(sum(x.predicted for x in xs)/n,4) if n else None
        rate=round(sum(x.label for x in xs)/n,4) if n else None
        err=round(abs(mean_p-rate),4) if n else None
        verdict='insufficient' if n<MIN_PART_SAMPLE else 'exceeded' if err>MAX_CALIBRATION_ERROR else 'warn' if err>=WARN_CALIBRATION_ERROR else 'ok'
        out.append({'part':part,'sample_size':n,'mean_predicted':mean_p,'actual_rate':rate,'calibration_error':err,'verdict':verdict})
    return out

def run_evaluation(actor='health-worker'):
    # 阶段一：分批采集入窗样本，每批独立提交；评估中断后重跑从断点继续，claim_id 唯一键保证不重复计数
    while True:
        with Session.begin() as s:
            v=s.scalar(select(ModelVersion).where(ModelVersion.state=='active'))
            if not v:return None
            if collect_batch(s,window_for(s,v))==0:break
    # 阶段二：持版本行锁完成快照与冻结判定，与受理/解冻互斥，原子切换只保留一套结果
    with Session.begin() as s:
        v=active_version(s)
        if not v:return None
        w=window_for(s,v)
        samples=s.scalars(select(HealthSample).where(HealthSample.window_id==w.id)).all()
        parts=part_stats(samples)
        w.sample_total=len(samples);w.parts_json=json.dumps(parts,ensure_ascii=False);w.evaluated_at=now()
        bad=[p for p in parts if p['verdict'] in ('insufficient','exceeded')]
        if bad:
            reason='；'.join(('样本不足' if p['verdict']=='insufficient' else '校准误差超限')+f"（{p['part']} 样本 {p['sample_size']}"+(f"，误差 {p['calibration_error']}" if p['calibration_error'] is not None else '')+'）' for p in bad)
            v.state='frozen';v.active_flag=None;v.frozen_at=now();v.freeze_reason=reason
            w.state='locked';w.locked_at=now()
            audit(s,{'email':actor},'version_frozen',f'v{v.version_no} {reason}')
        else:audit(s,{'email':actor},'health_evaluated',f'v{v.version_no} 窗口样本 {w.sample_total} 条，各部位校准误差在限值内')
        return {'version_no':v.version_no,'state':v.state,'sample_total':w.sample_total,'parts':parts}

def unfreeze(s,note,u):
    v=s.scalar(select(ModelVersion).where(ModelVersion.state=='frozen').with_for_update())
    if not v:raise HTTPException(409,'当前没有处于冻结状态的模型版本')
    v.state='retired';v.retired_at=now();v.unfreeze_note=note
    new=ModelVersion(version_no=v.version_no+1,state='active',active_flag=1,created_by=u['email'],created_at=now())
    s.add(new);s.flush();s.add(HealthWindow(version_id=new.id,state='open'))
    audit(s,u,'version_unfrozen',f'v{v.version_no} → v{new.version_no}：{note}')
    return health_view(s)

def version_view(s,v):
    d=obj(v);w=s.scalar(select(HealthWindow).where(HealthWindow.version_id==v.id))
    d['window_state']=w.state if w else None;return d

def health_view(s):
    versions=s.scalars(select(ModelVersion).order_by(ModelVersion.version_no.desc())).all()
    active=next((v for v in versions if v.state=='active'),None)
    frozen=next((v for v in versions if v.state=='frozen'),None)
    shown=active or frozen;window=None
    if shown:
        w=s.scalar(select(HealthWindow).where(HealthWindow.version_id==shown.id))
        if w:window={'id':w.id,'state':w.state,'sample_total':w.sample_total,'evaluated_at':w.evaluated_at,'locked_at':w.locked_at,'parts':json.loads(w.parts_json) if w.parts_json else [],'pending':pending_count(s)}
    return {'limits':{'min_part_sample':MIN_PART_SAMPLE,'max_calibration_error':MAX_CALIBRATION_ERROR,'warn_calibration_error':WARN_CALIBRATION_ERROR},
        'active_version':version_view(s,active) if active else None,'frozen_version':version_view(s,frozen) if frozen else None,
        'window':window,'versions':[version_view(s,v) for v in versions]}
