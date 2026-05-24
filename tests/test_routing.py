import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.models.alert import Severity


def make_mock_rule(priority, match_severity=None,
                   match_service=None, match_team=None,
                   route_to="test-team"):
    """Helper — creates a mock RoutingRule."""
    rule = MagicMock()
    rule.priority = priority
    rule.match_severity = match_severity
    rule.match_service = match_service
    rule.match_team = match_team
    rule.route_to = route_to
    rule.policy_id = None
    return rule


def make_mock_alert(severity="SEV1", service="payments", team="payments"):
    """Helper — creates a mock Alert."""
    alert = MagicMock()
    alert.severity = MagicMock()
    alert.severity.value = severity
    alert.service = service
    alert.team = team
    alert.id = "test-id"
    alert.title = "Test alert"
    alert.routed_to = None
    alert.status = None
    return alert


@pytest.mark.asyncio
async def test_sev1_matches_severity_rule():
    """SEV1 alert should match a rule with match_severity=SEV1."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV1")
    rule = make_mock_rule(priority=10, match_severity="SEV1",
                          route_to="platform-oncall")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rule]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "platform-oncall"


@pytest.mark.asyncio
async def test_service_rule_matches_correctly():
    """Alert from payments service should match payments rule."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV2", service="payments")
    rule = make_mock_rule(priority=20, match_service="payments",
                          route_to="payments-team")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rule]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "payments-team"


@pytest.mark.asyncio
async def test_first_matching_rule_wins():
    """When multiple rules match, lowest priority number wins."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV1", service="payments")

    rule1 = make_mock_rule(priority=10, match_severity="SEV1",
                           route_to="platform-oncall")
    rule2 = make_mock_rule(priority=20, match_service="payments",
                           route_to="payments-team")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rule1, rule2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "platform-oncall"


@pytest.mark.asyncio
async def test_no_matching_rule_uses_default():
    """When no rule matches, alert routes to default-oncall."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV3", service="unknown-service", team=None)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "default-oncall"


@pytest.mark.asyncio
async def test_team_rule_matches_correctly():
    """Alert from infra team should match infra rule."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV2", service="any-service", team="infra")
    rule = make_mock_rule(priority=30, match_team="infra",
                          route_to="infra-oncall")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rule]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "infra-oncall"


@pytest.mark.asyncio
async def test_wrong_severity_rule_does_not_match():
    """SEV2 alert should not match a SEV1-only rule."""
    from app.services.routing import route_alert

    alert = make_mock_alert(severity="SEV2")
    rule = make_mock_rule(priority=10, match_severity="SEV1",
                          route_to="platform-oncall")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [rule]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.routing.schedule_escalation", new_callable=AsyncMock):
        await route_alert(alert, mock_db)

    assert alert.routed_to == "default-oncall"