import json,time,os,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from .database import Session
from .models import Claim,Machine
from .health_models import ClaimRoute,ModelVersion
from .risk_model import assess
from .health_service import run_evaluation
r=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
while True:
    Path('/artifacts/worker-heartbeat').write_text(str(time.time()))
    item=r.blpop(['claim-risk','model-health-eval'],timeout=2)
    if not item:continue
    queue,raw=item
    if queue=='model-health-eval':
        try:
            snap=run_evaluation()
            if snap:Path('/artifacts/health-latest.json').write_text(json.dumps(snap,ensure_ascii=False))
        except Exception:logging.exception('health evaluation failed')
        continue
    cid=int(raw)
    try:
        with Session.begin() as s:
            c=s.get(Claim,cid)
            if not c or c.status!='queued':continue
            m=s.get(Machine,c.machine_id)
            if c.hours_at_failure>m.warranty_hours:c.status='out_of_warranty';c.assessment_note='超出质保工时';continue
            c.risk,metrics=assess(s,c)
            route=s.scalar(select(ClaimRoute).where(ClaimRoute.claim_id==c.id))
            if route and route.version_id:
                v=s.get(ModelVersion,route.version_id)
                if v:metrics['model_version']=v.version_no
            c.status='assessed';c.assessment_note=json.dumps(metrics,ensure_ascii=False)
            Path(f'/artifacts/claim-{cid}-model.json').write_text(json.dumps(metrics))
    except Exception as e:
        with Session.begin() as s:
            c=s.get(Claim,cid)
            if c:c.status='failed';c.assessment_note=str(e)
