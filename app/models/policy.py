import uuid

from sqlalchemy import Column, String, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.db.database import Base


class EscalationPolicy(Base):
    __tablename__ = "escalation_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    severity = Column(String, nullable=False)        # SEV1, SEV2, SEV3, SEV4
    wait_seconds = Column(Integer, default=0)        # 0 = notify immediately
    notify_channel = Column(String, nullable=False)  # "pagerduty", "slack", "email"
    notify_target = Column(String, nullable=False)   # channel ID, email address, etc
    conditions = Column(JSON, default={})            # optional extra filters


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    priority = Column(Integer, default=100)          # lower number = checked first
    match_service = Column(String, nullable=True)    # None = match any service
    match_team = Column(String, nullable=True)       # None = match any team
    match_severity = Column(String, nullable=True)   # None = match any severity
    route_to = Column(String, nullable=False)        # team or channel to route to
    policy_id = Column(String, nullable=True)        # links to EscalationPolicy