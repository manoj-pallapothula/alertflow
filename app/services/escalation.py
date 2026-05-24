import asyncio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.alert import Alert, Severity
from app.models.policy import EscalationPolicy
from app.config import settings


DEFAULT_POLICIES = {
    "SEV1": {
        "wait_seconds": 0,
        "channel": "slack",
        "target": "#alerts",
    },
    "SEV2": {
        "wait_seconds": 300,
        "channel": "slack",
        "target": "#alerts",
    },
    "SEV3": {
        "wait_seconds": 900,
        "channel": "slack",
        "target": "#alerts",
    },
    "SEV4": {
        "wait_seconds": 0,
        "channel": "slack",
        "target": "#alerts",
    },
}

# Color per severity — shows as left border on Slack message
SEV_COLORS = {
    "SEV1": "#E02020",   # red
    "SEV2": "#F59E0B",   # amber
    "SEV3": "#1A56DB",   # blue
    "SEV4": "#10B981",   # green
}

SEV_EMOJI = {
    "SEV1": "🔴",
    "SEV2": "🟡",
    "SEV3": "🔵",
    "SEV4": "🟢",
}


async def schedule_escalation(
    alert: Alert,
    policy_id: str | None,
    db: AsyncSession
):
    policy = None

    if policy_id:
        result = await db.execute(
            select(EscalationPolicy).where(
                EscalationPolicy.id == policy_id
            )
        )
        policy = result.scalar_one_or_none()

    if policy:
        wait = policy.wait_seconds
        channel = policy.notify_channel
        target = policy.notify_target
    else:
        defaults = DEFAULT_POLICIES.get(
            alert.severity.value,
            DEFAULT_POLICIES["SEV3"]
        )
        wait = defaults["wait_seconds"]
        channel = defaults["channel"]
        target = defaults["target"]

    if wait == 0:
        await fire_notification(alert, channel, target)
    else:
        asyncio.create_task(
            delayed_notification(alert, channel, target, wait)
        )


async def delayed_notification(
    alert: Alert,
    channel: str,
    target: str,
    wait_seconds: int
):
    print(f"[ESCALATION] Waiting {wait_seconds}s before notifying "
          f"for {alert.severity.value}: {alert.title}")
    await asyncio.sleep(wait_seconds)
    await fire_notification(alert, channel, target)


async def fire_notification(alert: Alert, channel: str, target: str):
    """
    Send alert notification to Slack.
    Falls back to terminal print if no webhook URL is configured.
    """
    if not settings.slack_webhook_url:
        # Fallback — print to terminal if no webhook configured
        print(
            f"\n[NOTIFY] {channel} → {target}\n"
            f"  {alert.severity.value} | {alert.service} | {alert.title}\n"
        )
        return

    emoji = SEV_EMOJI.get(alert.severity.value, "⚪")
    color = SEV_COLORS.get(alert.severity.value, "#888888")

    # Build Slack message with attachment for colored sidebar
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {alert.severity.value} — {alert.title}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service*\n{alert.service}"},
                    {"type": "mrkdwn", "text": f"*Team*\n{alert.team or 'unassigned'}"},
                    {"type": "mrkdwn", "text": f"*Routed To*\n{alert.routed_to or 'default-oncall'}"},
                    {"type": "mrkdwn", "text": f"*Source*\n{alert.source}"},
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Alert ID:* `{alert.id}`"
                }
            },
            {
                "type": "divider"
            }
        ]
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.slack_webhook_url,
                json=payload,
                timeout=10.0,
            )
            if response.status_code == 200:
                print(f"[SLACK] ✅ Notification sent for {alert.severity.value}: {alert.title}")
            else:
                print(f"[SLACK] ❌ Failed — status {response.status_code}: {response.text}")

    except Exception as e:
        print(f"[SLACK] ❌ Error sending notification: {e}")