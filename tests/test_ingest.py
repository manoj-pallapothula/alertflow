import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
from datetime import datetime


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Create a test client with mocked database and Redis."""
    with patch("app.db.database.engine"), \
         patch("app.db.database.AsyncSessionLocal"):
        from app.main import app
        return TestClient(app)


def make_mock_alert(deduplicated=False, status="routed"):
    """Helper — returns a mock Alert object."""
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.title = "Test alert"
    alert.severity = MagicMock()
    alert.severity.value = "SEV1"
    alert.service = "payments"
    alert.is_deduplicated = deduplicated
    alert.routed_to = "platform-oncall"
    alert.status = MagicMock()
    alert.status.value = status
    return alert


# ── Health checks ─────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    """Health endpoint should always return 200."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ingest_health(client):
    """Ingest health check should return ok."""
    response = client.get("/ingest/health")
    assert response.status_code == 200


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_prometheus_requires_api_key(client):
    """POST without API key should return 401."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.api_key = "test-secret-key"
        mock_settings.dedup_window_seconds = 300
        mock_settings.slack_webhook_url = None

        response = client.post(
            "/ingest/prometheus",
            json={
                "version": "4",
                "alerts": [{
                    "labels": {"alertname": "Test", "severity": "critical"},
                    "annotations": {"summary": "Test"},
                    "startsAt": "2024-01-01T00:00:00Z"
                }]
            }
        )
        assert response.status_code == 401


# ── Prometheus normalization ───────────────────────────────────────────────────

def test_normalize_prometheus_maps_severity():
    """Prometheus severity strings should map to SEV levels."""
    from app.routers.ingest import normalize_prometheus
    from app.models.alert import PrometheusWebhook

    webhook = PrometheusWebhook(alerts=[
        {
            "labels": {
                "alertname": "HighCPU",
                "severity": "critical",
                "job": "api-server"
            },
            "annotations": {"summary": "CPU high"},
            "startsAt": "2024-01-01T00:00:00Z"
        }
    ])

    alerts = normalize_prometheus(webhook)
    assert len(alerts) == 1
    assert alerts[0].severity == "SEV1"
    assert alerts[0].service == "api-server"
    assert alerts[0].source == "prometheus"


def test_normalize_prometheus_warning_maps_to_sev2():
    """Warning severity should map to SEV2."""
    from app.routers.ingest import normalize_prometheus
    from app.models.alert import PrometheusWebhook

    webhook = PrometheusWebhook(alerts=[
        {
            "labels": {"alertname": "SlowQuery", "severity": "warning", "job": "db"},
            "annotations": {"summary": "Slow queries"},
            "startsAt": "2024-01-01T00:00:00Z"
        }
    ])

    alerts = normalize_prometheus(webhook)
    assert alerts[0].severity == "SEV2"


def test_normalize_prometheus_fingerprint_is_stable():
    """Same labels should always produce same fingerprint."""
    from app.routers.ingest import normalize_prometheus
    from app.models.alert import PrometheusWebhook

    labels = {"alertname": "Test", "severity": "critical", "job": "payments"}
    webhook = PrometheusWebhook(alerts=[
        {
            "labels": labels,
            "annotations": {"summary": "Test"},
            "startsAt": "2024-01-01T00:00:00Z"
        }
    ])

    alerts1 = normalize_prometheus(webhook)
    alerts2 = normalize_prometheus(webhook)

    assert alerts1[0].fingerprint == alerts2[0].fingerprint


def test_normalize_prometheus_multiple_alerts():
    """Webhook with multiple alerts should return multiple AlertCreate objects."""
    from app.routers.ingest import normalize_prometheus
    from app.models.alert import PrometheusWebhook

    webhook = PrometheusWebhook(alerts=[
        {
            "labels": {"alertname": "Alert1", "severity": "critical", "job": "svc1"},
            "annotations": {"summary": "Alert 1"},
            "startsAt": "2024-01-01T00:00:00Z"
        },
        {
            "labels": {"alertname": "Alert2", "severity": "warning", "job": "svc2"},
            "annotations": {"summary": "Alert 2"},
            "startsAt": "2024-01-01T00:00:00Z"
        }
    ])

    alerts = normalize_prometheus(webhook)
    assert len(alerts) == 2
    assert alerts[0].severity == "SEV1"
    assert alerts[1].severity == "SEV2"


# ── PagerDuty normalization ────────────────────────────────────────────────────

def test_normalize_pagerduty_maps_severity():
    """PagerDuty critical should map to SEV1."""
    from app.routers.ingest import normalize_pagerduty
    from app.models.alert import PagerDutyAlert

    pd = PagerDutyAlert(
        routing_key="key123",
        event_action="trigger",
        dedup_key="pd-001",
        payload={
            "summary": "Database down",
            "severity": "critical",
            "source": "db-monitor",
        }
    )

    alert = normalize_pagerduty(pd)
    assert alert.severity == "SEV1"
    assert alert.source == "pagerduty"
    assert alert.fingerprint == "pd-001"


def test_normalize_pagerduty_uses_dedup_key_as_fingerprint():
    """PagerDuty dedup_key should be used as fingerprint when provided."""
    from app.routers.ingest import normalize_pagerduty
    from app.models.alert import PagerDutyAlert

    pd = PagerDutyAlert(
        routing_key="key",
        event_action="trigger",
        dedup_key="my-unique-key",
        payload={"summary": "Test", "severity": "warning", "source": "monitor"}
    )

    alert = normalize_pagerduty(pd)
    assert alert.fingerprint == "my-unique-key"