import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from pydantic import BaseModel
from typing import Optional

from app.db.database import Base


class TimelineEventType(str, enum.Enum):
    RECEIVED        = "received"
    DEDUPLICATED    = "deduplicated"
    ROUTED          = "routed"
    ESCALATED       = "escalated"
    NOTIFIED        = "notified"
    ACKNOWLEDGED    = "acknowledged"
    RESOLVED        = "resolved"
    COMMENT         = "comment"


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(Enum(TimelineEventType), nullable=False)
    message    = Column(String, nullable=False)
    details    = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TimelineEventResponse(BaseModel):
    id:         str
    alert_id:   str
    event_type: str
    message:    str
    details:    dict
    created_at: str

    class Config:
        from_attributes = True


class AddCommentRequest(BaseModel):
    message: str
    author:  Optional[str] = "anonymous"