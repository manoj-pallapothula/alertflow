from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.alert import Alert, AlertStatus
from app.models.policy import RoutingRule
from app.services.escalation import schedule_escalation
from app.services import timeline as tl


async def route_alert(alert: Alert, db: AsyncSession):
    """
    Match alert against routing rules in priority order.
    First matching rule wins.
    """
    result = await db.execute(
        select(RoutingRule).order_by(RoutingRule.priority)
    )
    rules = result.scalars().all()

    matched_rule = None
    for rule in rules:
        if rule.match_severity and rule.match_severity != alert.severity.value:
            continue
        if rule.match_service and rule.match_service not in alert.service:
            continue
        if rule.match_team and rule.match_team != alert.team:
            continue
        matched_rule = rule
        break

    if matched_rule:
        alert.routed_to = matched_rule.route_to
        alert.status = AlertStatus.ROUTED
        await db.commit()

        # Record routing event
        await tl.record_routed(
            db, alert.id,
            matched_rule.route_to,
            matched_rule.priority
        )

        await schedule_escalation(alert, matched_rule.policy_id, db)
    else:
        alert.routed_to = "default-oncall"
        alert.status = AlertStatus.ROUTED
        await db.commit()

        # Record routing event
        await tl.record_routed(db, alert.id, "default-oncall")
        await schedule_escalation(alert, None, db)

    return alert