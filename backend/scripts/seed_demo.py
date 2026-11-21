import random, json, logging
from datetime import datetime,timezone
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,Machine,Claim,Inspection
from src.security import password_hash
from src.return_models import PartReturn
from src.settlement_models import Settlement
from src.repair_models import RepairBay,RepairAppointment
from src.spare_models import SpareStock,PartIssue
from src.followup_models import RepairFollowup
from src.health_models import ModelVersion,HealthWindow,HealthSample,ClaimRoute

def seed():
    Base.metadata.create_all(engine)
    with Session.begin() as s:
        for role in ['admin','assessor','viewer']:
            if not s.scalar(select(User).where(User.email==f'{role}@gengchuan.local')):s.add(User(email=f'{role}@gengchuan.local',password=password_hash('Field2026!'),role=role))
        for serial,model,hours in [('GC-2408','Paddy-90',860),('GC-2412','Dryland-120',1120),('GC-EXPIRED','Paddy-90',2450)]:
            if not s.scalar(select(Machine).where(Machine.serial==serial)):s.add(Machine(serial=serial,model=model,purchase_date='2025-04-12',warranty_hours=2000,hours=hours))
        s.flush(); machines=s.scalars(select(Machine).order_by(Machine.id)).all()
        rng=random.Random(42)
        for i in range(180):
            code=f'HIST-{i:04}'
            if s.scalar(select(Claim).where(Claim.code==code)):continue
            hours=rng.randint(100,2900); age=rng.randint(30,1100); leak=rng.random()<.38; part=rng.choice(['hydraulic','engine','transmission'])
            score=hours/2000+age/1300+(.7 if leak else 0)+(.3 if part=='hydraulic' else 0)+rng.uniform(-.25,.25)
            s.add(Claim(code=code,machine_id=machines[i%2].id,part=part,hours_at_failure=hours,age_days=age,leak_flag=leak,risk=None,status='denied' if score>1.7 else 'paid',historical=True,disputed=int(score>1.7),assessment_note='历史已结案 / 模拟训练数据'))
        for code,serial,hours,age,leak in [('CL-26017','GC-2408',860,400,True),('CL-HIGH','GC-2412',1900,680,True),('CL-EXPIRED','GC-EXPIRED',2450,600,False)]:
            if not s.scalar(select(Claim).where(Claim.code==code)):
                m=s.scalar(select(Machine).where(Machine.serial==serial));s.add(Claim(code=code,machine_id=m.id,part='hydraulic',hours_at_failure=hours,age_days=age,leak_flag=leak,status='submitted',historical=False,assessment_note=''))
    with Session.begin() as s:
        m=s.scalar(select(Machine).where(Machine.serial=='GC-2408'))
        for code in ['CL-RETURN-DEMO','CL-SETTLE-DEMO']:
            c=s.scalar(select(Claim).where(Claim.code==code))
            if not c:
                c=Claim(code=code,machine_id=m.id,part='hydraulic',hours_at_failure=860,age_days=400,leak_flag=True,risk=.65,status='paid',historical=False,assessment_note='模拟赔付结案，用于返厂和结算剧本');s.add(c);s.flush()
                s.add(Inspection(claim_id=c.id,findings='密封圈异常磨损，工时及拆检资料已核验完整',evidence_complete=True,decision='paid'))
        c=s.scalar(select(Claim).where(Claim.code=='CL-SETTLE-DEMO'))
        if not s.scalar(select(PartReturn).where(PartReturn.claim_id==c.id)):
            s.add(PartReturn(claim_id=c.id,tracking_code='RT-DEMO-SETTLE',expected_serial=m.serial,received_serial=m.serial,condition='油封拆件封袋完好，序列与原始索赔匹配',state='verified',verified_by='admin@gengchuan.local'))
    with Session.begin() as s:
        for code,cap,active in [('BAY-HYD',8,True),('BAY-QUICK',4,True),('BAY-OFF',8,False)]:
            if not s.scalar(select(RepairBay).where(RepairBay.code==code)):s.add(RepairBay(code=code,daily_hours=cap,active=active))
        for code,part,qty in [('SP-HYD-01','hydraulic',20),('SP-ENG-01','engine',5),('SP-TRANS-01','transmission',3)]:
            if not s.scalar(select(SpareStock).where(SpareStock.code==code)):s.add(SpareStock(code=code,part=part,available_qty=qty))
    with Session.begin() as s:
        machines=s.scalars(select(Machine).order_by(Machine.id)).all()
        stamp=datetime.now(timezone.utc).isoformat()
        v=s.scalar(select(ModelVersion).where(ModelVersion.version_no==1))
        if not v:
            v=ModelVersion(version_no=1,state='active',active_flag=1,created_by='seed@gengchuan.local',created_at=stamp);s.add(v);s.flush()
            s.add(HealthWindow(version_id=v.id,state='open'))
        for code in ['CL-26017','CL-HIGH','CL-RETURN-DEMO','CL-SETTLE-DEMO']:
            c=s.scalar(select(Claim).where(Claim.code==code))
            if c and not s.scalar(select(ClaimRoute).where(ClaimRoute.claim_id==c.id)):
                s.add(ClaimRoute(claim_id=c.id,version_id=v.id,mode='model',created_at=stamp))
        i=0
        for part,(risks,disputed_n) in {'hydraulic':([.42,.48,.5,.55,.58,.6,.62,.65,.7,.75],6),'engine':([.15,.2,.22,.25,.28,.3,.32,.35,.38,.4],3),'transmission':([.3,.32,.35,.38,.4,.42,.45,.48,.5,.55],6)}.items():
            for j,risk in enumerate(risks):
                i+=1;code=f'CL-W-{i:03}'
                c=s.scalar(select(Claim).where(Claim.code==code))
                if not c:
                    disputed=int(j>=len(risks)-disputed_n)
                    c=Claim(code=code,machine_id=machines[i%2].id,part=part,hours_at_failure=int(300+risk*1500),age_days=int(100+risk*600),leak_flag=risk>=.5,risk=risk,status='denied' if disputed else 'paid',historical=False,disputed=disputed,assessment_note='模型健康窗口样本 / 模拟评分结案');s.add(c);s.flush()
                if not s.scalar(select(ClaimRoute).where(ClaimRoute.claim_id==c.id)):
                    s.add(ClaimRoute(claim_id=c.id,version_id=v.id,mode='model',created_at=stamp))
    try:
        from src.health_service import run_evaluation,pending_exists
        if pending_exists():run_evaluation(actor='seed@gengchuan.local')
    except Exception:logging.exception('health window evaluation failed')
    with Session() as s:
        print(json.dumps({k:s.scalar(select(func.count()).select_from(v)) for k,v in [('users',User),('machines',Machine),('claims',Claim),('inspections',Inspection),('part_returns',PartReturn),('settlements',Settlement),('repair_bays',RepairBay),('repair_appointments',RepairAppointment),('spare_stocks',SpareStock),('part_issues',PartIssue),('repair_followups',RepairFollowup),('model_versions',ModelVersion),('health_windows',HealthWindow),('health_samples',HealthSample),('claim_routes',ClaimRoute)]}))
if __name__=='__main__':seed()
