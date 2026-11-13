from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Index
from sqlalchemy.sql import func

from ..database import Base, JSONType, UTCDateTime
from ..tenant.mixin import TenantMixin


class CircuitIncident(TenantMixin, Base):
    __tablename__ = "circuit_incidents"
    __table_args__ = (
        Index('ix_circuit_incidents_status_started', 'status', 'started_at'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    circuit_id = Column(Integer, ForeignKey("circuits.id"), nullable=False)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), default="minor")
    status = Column(String(20), default="open")
    started_at = Column(UTCDateTime, nullable=False)
    resolved_at = Column(UTCDateTime)
    duration_minutes = Column(Integer)
    symptom = Column(Text)
    root_cause = Column(Text)
    resolution = Column(Text)
    affected_sites = Column(JSONType)
    reported_by = Column(String(50))
    ticket_no = Column(String(50))
    created_at = Column(UTCDateTime, server_default=func.now())
    updated_at = Column(UTCDateTime, onupdate=func.now())


class CircuitIncidentLog(TenantMixin, Base):
    __tablename__ = "circuit_incident_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("circuit_incidents.id"))
    content = Column(Text, nullable=False)
    operator = Column(String(50))
    created_at = Column(UTCDateTime, server_default=func.now())
