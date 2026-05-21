import uuid
import enum
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import Column, String, DateTime, Enum, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from pydantic import BaseModel

from app.db.database import Base


# --- Enums --- #

class Severity(str, enum.Enum):
    SEV1 = "SEV1"   # Critical — page immediately
    SEV2 = "SEV2"   # High — 5 min wait
    SEV3 = "SEV3"   # Medium — 15 min wait
    SEV4 = "SEV4"   # Low — email only


class AlertStatus(str, enum.Enum):
    ACTIVE = "active"
    DEDUPLICATED = "deduplicated"
    ROUTED = "routed"
    RESOLVED = "resolved"


# --- Database Table --- #

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)        # "prometheus" or "pagerduty"
    severity = Column(Enum(Severity), nullable=False)
    service = Column(String, nullable=False)
    team = Column(String, nullable=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    labels = Column(JSON, default={})
    status = Column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    routed_to = Column(String, nullable=True)
    is_deduplicated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


# --- Pydantic Schemas (for validating incoming webhook data) --- #

class PrometheusAlert(BaseModel):
    labels: Dict[str, str]
    annotations: Dict[str, str] = {}
    startsAt: str
    endsAt: Optional[str] = None


class PrometheusWebhook(BaseModel):
    version: str = "4"
    alerts: list[PrometheusAlert]


class PagerDutyAlert(BaseModel):
    routing_key: str
    event_action: str
    dedup_key: Optional[str] = None
    payload: Dict[str, Any]


class AlertCreate(BaseModel):
    fingerprint: str
    source: str
    severity: str
    service: str
    team: Optional[str] = None
    title: str
    description: Optional[str] = None
    labels: Dict[str, Any] = {}