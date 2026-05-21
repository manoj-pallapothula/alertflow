from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.alert import Alert, AlertStatus
from app.models.policy import RoutingRule
from app.services.escalation import schedule_escalation


async def route_alert(alert: Alert, db: AsyncSession):
    """
    Match an alert against routing rules in priority order.
    First matching rule wins.
    If no rule matches, route to default catch-all.
    """

    # Load all rules ordered by priority (lowest number = checked first)
    result = await db.execute(
        select(RoutingRule).order_by(RoutingRule.priority)
    )
    rules = result.scalars().all()

    matched_rule = None

    for rule in rules:
        # Check severity match — skip if rule specifies a severity and it doesn't match
        if rule.match_severity and rule.match_severity != alert.severity.value:
            continue

        # Check service match — skip if rule specifies a service and it doesn't match
        if rule.match_service and rule.match_service not in alert.service:
            continue

        # Check team match — skip if rule specifies a team and it doesn't match
        if rule.match_team and rule.match_team != alert.team:
            continue

        # All conditions passed — this rule matches
        matched_rule = rule
        break

    if matched_rule:
        alert.routed_to = matched_rule.route_to
        alert.status = AlertStatus.ROUTED
        await db.commit()

        # Trigger escalation using the rule's linked policy
        await schedule_escalation(alert, matched_rule.policy_id, db)

    else:
        # No rule matched — use default catch-all
        alert.routed_to = "default-oncall"
        alert.status = AlertStatus.ROUTED
        await db.commit()

        # Trigger escalation with no specific policy — uses defaults
        await schedule_escalation(alert, None, db)

    return alert