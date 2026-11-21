from sqlalchemy import String, Integer, Float, ForeignKey, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
class ModelVersion(Base):
    __tablename__='model_versions'
    __table_args__=(CheckConstraint("state in ('active','frozen','retired')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    version_no:Mapped[int]=mapped_column(unique=True)
    state:Mapped[str]=mapped_column(String(20),default='active')
    active_flag:Mapped[int|None]=mapped_column(Integer,nullable=True,unique=True)
    created_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40),default='')
    frozen_at:Mapped[str]=mapped_column(String(40),default='')
    freeze_reason:Mapped[str]=mapped_column(Text,default='')
    retired_at:Mapped[str]=mapped_column(String(40),default='')
    unfreeze_note:Mapped[str]=mapped_column(Text,default='')
class HealthWindow(Base):
    __tablename__='health_windows'
    __table_args__=(CheckConstraint("state in ('open','locked')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    version_id:Mapped[int]=mapped_column(ForeignKey('model_versions.id'),unique=True)
    state:Mapped[str]=mapped_column(String(20),default='open')
    sample_total:Mapped[int]=mapped_column(Integer,default=0)
    parts_json:Mapped[str]=mapped_column(Text,default='')
    evaluated_at:Mapped[str]=mapped_column(String(40),default='')
    locked_at:Mapped[str]=mapped_column(String(40),default='')
class HealthSample(Base):
    __tablename__='health_samples'
    id:Mapped[int]=mapped_column(primary_key=True)
    window_id:Mapped[int]=mapped_column(ForeignKey('health_windows.id'))
    claim_id:Mapped[int]=mapped_column(ForeignKey('claims.id'),unique=True)
    part:Mapped[str]=mapped_column(String(40))
    predicted:Mapped[float]=mapped_column(Float)
    label:Mapped[int]=mapped_column(Integer)
class ClaimRoute(Base):
    __tablename__='claim_routes'
    __table_args__=(CheckConstraint("mode in ('model','manual')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    claim_id:Mapped[int]=mapped_column(ForeignKey('claims.id'),unique=True)
    version_id:Mapped[int|None]=mapped_column(ForeignKey('model_versions.id'),nullable=True)
    mode:Mapped[str]=mapped_column(String(20))
    note:Mapped[str]=mapped_column(String(200),default='')
    created_at:Mapped[str]=mapped_column(String(40),default='')
