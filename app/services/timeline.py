from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.timeline import TimelineEvent, TimelineEventType


async def add_event(
    db: AsyncSession,
    alert_id: str,
    event_type: TimelineEventType,
    message: str,
    details: dict = None,
):
    """Add a timeline event for an alert."""
    event = TimelineEvent(
        alert_id=alert_id,
        event_type=event_type,
        message=message,
        details=details or {},
    )
    db.add(event)
    await db.commit()
    return event


async def get_timeline(db: AsyncSession, alert_id: str) -> list[TimelineEvent]:
    """Get all timeline events for an alert ordered by time."""
    result = await db.execute(
        select(TimelineEvent)
        .where(TimelineEvent.alert_id == alert_id)
        .order_by(TimelineEvent.created_at.asc())
    )
    return result.scalars().all()


# ── Event helpers ─────────────────────────────────────────────────────────────

async def record_received(db, alert_id, source, severity, service):
    await add_event(db, alert_id, TimelineEventType.RECEIVED,
        f"Alert received from {source}",
        {"source": source, "severity": severity, "service": service})


async def record_deduplicated(db, alert_id, fingerprint):
    await add_event(db, alert_id, TimelineEventType.DEDUPLICATED,
        "Alert deduplicated — duplicate of existing alert",
        {"fingerprint": fingerprint})


async def record_routed(db, alert_id, routed_to, rule_priority=None):
    await add_event(db, alert_id, TimelineEventType.ROUTED,
        f"Routed to {routed_to}",
        {"routed_to": routed_to, "rule_priority": rule_priority})


async def record_escalated(db, alert_id, severity, wait_seconds, channel):
    wait_msg = "immediately" if wait_seconds == 0 else f"after {wait_seconds}s"
    await add_event(db, alert_id, TimelineEventType.ESCALATED,
        f"Escalation triggered — notifying {wait_msg} via {channel}",
        {"severity": severity, "wait_seconds": wait_seconds,
         "channel": channel})


async def record_notified(db, alert_id, channel, target):
    await add_event(db, alert_id, TimelineEventType.NOTIFIED,
        f"Notification sent via {channel} to {target}",
        {"channel": channel, "target": target})


async def record_resolved(db, alert_id):
    await add_event(db, alert_id, TimelineEventType.RESOLVED,
        "Alert resolved",
        {"resolved_at": datetime.utcnow().isoformat()})