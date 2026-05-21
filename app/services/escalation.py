import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.alert import Alert, Severity
from app.models.policy import EscalationPolicy


# Default policies used when no policy is configured in the database
DEFAULT_POLICIES = {
    "SEV1": {
        "wait_seconds": 0,
        "channel": "pagerduty",
        "target": "oncall-primary",
    },
    "SEV2": {
        "wait_seconds": 300,      # 5 minutes
        "channel": "slack",
        "target": "#alerts-sev2",
    },
    "SEV3": {
        "wait_seconds": 900,      # 15 minutes
        "channel": "slack",
        "target": "#alerts-sev3",
    },
    "SEV4": {
        "wait_seconds": 0,
        "channel": "email",
        "target": "alerts@yourcompany.com",
    },
}


async def schedule_escalation(
    alert: Alert,
    policy_id: str | None,
    db: AsyncSession
):
    """
    Look up the escalation policy and fire or schedule the notification.
    If no policy_id is given, falls back to DEFAULT_POLICIES based on severity.
    """

    policy = None

    # Try to load a custom policy from the database
    if policy_id:
        result = await db.execute(
            select(EscalationPolicy).where(
                EscalationPolicy.id == policy_id
            )
        )
        policy = result.scalar_one_or_none()

    # Use custom policy if found, otherwise fall back to defaults
    if policy:
        wait = policy.wait_seconds
        channel = policy.notify_channel
        target = policy.notify_target
    else:
        severity_key = alert.severity.value
        defaults = DEFAULT_POLICIES.get(severity_key, DEFAULT_POLICIES["SEV3"])
        wait = defaults["wait_seconds"]
        channel = defaults["channel"]
        target = defaults["target"]

    if wait == 0:
        # Notify immediately — don't block the request
        await fire_notification(alert, channel, target)
    else:
        # Schedule notification in the background
        # asyncio.create_task runs it without blocking the current request
        asyncio.create_task(
            delayed_notification(alert, channel, target, wait)
        )


async def delayed_notification(
    alert: Alert,
    channel: str,
    target: str,
    wait_seconds: int
):
    """
    Wait for the specified time then fire the notification.
    Runs in the background — the original request has already returned.
    """
    print(f"[ESCALATION] Waiting {wait_seconds}s before notifying "
          f"for {alert.severity.value} alert: {alert.title}")

    await asyncio.sleep(wait_seconds)

    # Check if alert was resolved during the wait period
    # (In a production system you'd re-query the DB here)
    await fire_notification(alert, channel, target)


async def fire_notification(alert: Alert, channel: str, target: str):
    """
    Send the actual notification.
    Currently prints to terminal — replace with real integrations later.

    TODO: Replace with:
    - Slack: POST to webhook URL
    - PagerDuty: POST to Events API v2
    - Email: send via SMTP or SendGrid
    """
    print(
        f"\n[NOTIFY] {'='*50}\n"
        f"  Channel  : {channel}\n"
        f"  Target   : {target}\n"
        f"  Severity : {alert.severity.value}\n"
        f"  Service  : {alert.service}\n"
        f"  Title    : {alert.title}\n"
        f"  Alert ID : {alert.id}\n"
        f"{'='*52}\n"
    )