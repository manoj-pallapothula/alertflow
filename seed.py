import asyncio
from app.db.database import AsyncSessionLocal
from app.models.policy import RoutingRule, EscalationPolicy


async def seed():
    async with AsyncSessionLocal() as db:

        # ── Escalation Policies ──────────────────────────────────────────
        print("Seeding escalation policies...")

        policies = [
            EscalationPolicy(
                name="SEV1 - Page Immediately",
                severity="SEV1",
                wait_seconds=0,
                notify_channel="pagerduty",
                notify_target="oncall-primary",
            ),
            EscalationPolicy(
                name="SEV2 - Slack after 5 min",
                severity="SEV2",
                wait_seconds=300,
                notify_channel="slack",
                notify_target="#alerts-sev2",
            ),
            EscalationPolicy(
                name="SEV3 - Slack after 15 min",
                severity="SEV3",
                wait_seconds=900,
                notify_channel="slack",
                notify_target="#alerts-sev3",
            ),
            EscalationPolicy(
                name="SEV4 - Email only",
                severity="SEV4",
                wait_seconds=0,
                notify_channel="email",
                notify_target="alerts@yourcompany.com",
            ),
        ]

        db.add_all(policies)
        await db.flush()  # flush to get IDs without committing yet
        print(f"  ✅ Added {len(policies)} escalation policies")

        # ── Routing Rules ────────────────────────────────────────────────
        print("Seeding routing rules...")

        rules = [
            # SEV1 anything → platform oncall immediately
            RoutingRule(
                priority=10,
                match_severity="SEV1",
                match_service=None,
                match_team=None,
                route_to="platform-oncall",
            ),
            # payments service → payments team
            RoutingRule(
                priority=20,
                match_severity=None,
                match_service="payments",
                match_team=None,
                route_to="payments-team",
            ),
            # infra team alerts → infra oncall
            RoutingRule(
                priority=30,
                match_severity=None,
                match_service=None,
                match_team="infra",
                route_to="infra-oncall",
            ),
            # api-server service → backend team
            RoutingRule(
                priority=40,
                match_severity=None,
                match_service="api-server",
                match_team=None,
                route_to="backend-team",
            ),
            # SEV2 anything → sev2 oncall
            RoutingRule(
                priority=50,
                match_severity="SEV2",
                match_service=None,
                match_team=None,
                route_to="sev2-oncall",
            ),
            # Catch-all — matches everything not caught above
            RoutingRule(
                priority=999,
                match_severity=None,
                match_service=None,
                match_team=None,
                route_to="default-oncall",
            ),
        ]

        db.add_all(rules)
        await db.commit()
        print(f"  ✅ Added {len(rules)} routing rules")

        print("\n🌱 Seed complete!")
        print("\nRouting rules summary:")
        print("  Priority 10  — SEV1 → platform-oncall")
        print("  Priority 20  — payments service → payments-team")
        print("  Priority 30  — infra team → infra-oncall")
        print("  Priority 40  — api-server → backend-team")
        print("  Priority 50  — SEV2 → sev2-oncall")
        print("  Priority 999 — everything else → default-oncall")


asyncio.run(seed())