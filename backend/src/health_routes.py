import os
from fastapi import APIRouter,Depends
from redis import Redis
from .database import Session
from .security import current,allow
from .schemas import UnfreezeIn
from . import health_service as health
router=APIRouter()
r=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
@router.get('/model-health')
def model_health(u=Depends(current)):
    with Session() as s:return health.health_view(s)
@router.post('/model-health/evaluate')
def evaluate(u=Depends(current)):
    allow(u,'admin','assessor')
    r.rpush('model-health-eval','run')
    return {'status':'queued'}
@router.post('/model-health/unfreeze')
def unfreeze(d:UnfreezeIn,u=Depends(current)):
    allow(u,'admin')
    with Session.begin() as s:return health.unfreeze(s,d.note,u)
