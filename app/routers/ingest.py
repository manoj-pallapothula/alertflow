import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.alert import (
    Alert, Severity, AlertStatus,
    PrometheusWebhook, PagerDutyAlert, AlertCreate
)
from app.services.dedup import check_and_mark_duplicate
from app.services.routing import route_alert
from app.security import verify_api_key

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


# ─── Normalizers ────────────────────────────────────────────────────────────

def normalize_prometheus(webhook: PrometheusWebhook) -> list[AlertCreate]:
    """
    Convert Prometheus webhook payload into internal AlertCreate objects.
    Prometheus sends a list of alerts in one webhook call.
    """
    alerts = []

    for pa in webhook.alerts:
        labels = pa.labels

        # Build a stable fingerprint from sorted labels
        # Same labels always produce the same fingerprint
        fingerprint = hashlib.md5(
            json.dumps(labels, sort_keys=True).encode()
        ).hexdigest()

        # Prometheus uses "critical/warning/info" — map to SEV1/SEV2/SEV3
        severity_raw = labels.get("severity", "warning").lower()
        severity_map = {
            "critical": "SEV1",
            "warning":  "SEV2",
            "info":     "SEV3",
        }
        severity = severity_map.get(severity_raw, "SEV3")

        alerts.append(AlertCreate(
            fingerprint=fingerprint,
            source="prometheus",
            severity=severity,
            service=labels.get("job", labels.get("service", "unknown")),
            team=labels.get("team"),
            title=pa.annotations.get(
                "summary",
                labels.get("alertname", "Unknown Alert")
            ),
            description=pa.annotations.get("description"),
            labels=labels,
        ))

    return alerts


def normalize_pagerduty(pd: PagerDutyAlert) -> AlertCreate:
    """
    Convert PagerDuty event payload into internal AlertCreate object.
    PagerDuty sends one event per webhook call.
    """
    payload = pd.payload

    # PagerDuty uses "critical/error/warning/info" — map to SEV1/SEV2/SEV3/SEV4
    severity_map = {
        "critical": "SEV1",
        "error":    "SEV2",
        "warning":  "SEV3",
        "info":     "SEV4",
    }
    severity = severity_map.get(
        payload.get("severity", "warning"),
        "SEV3"
    )

    # Use PagerDuty's dedup_key if provided, otherwise generate one
    fingerprint = pd.dedup_key or hashlib.md5(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()

    custom = payload.get("custom_details", {})

    return AlertCreate(
        fingerprint=fingerprint,
        source="pagerduty",
        severity=severity,
        service=payload.get("source", "unknown"),
        team=custom.get("team"),
        title=payload.get("summary", "PagerDuty Alert"),
        description=custom.get("description"),
        labels=payload,
    )


# ─── Core processing ────────────────────────────────────────────────────────

async def process_alert(alert_data: AlertCreate, db: AsyncSession) -> Alert:
    """
    Core pipeline for every alert regardless of source:
    1. Check for duplicate
    2. Save to database
    3. Route if not duplicate
    """

    # Step 1 — deduplication check
    is_dup = await check_and_mark_duplicate(alert_data.fingerprint)

    # Step 2 — save to database
    try:
        severity = Severity[alert_data.severity]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: {alert_data.severity}. "
                   f"Must be SEV1, SEV2, SEV3, or SEV4."
        )

    alert = Alert(
        fingerprint=alert_data.fingerprint,
        source=alert_data.source,
        severity=severity,
        service=alert_data.service,
        team=alert_data.team,
        title=alert_data.title,
        description=alert_data.description,
        labels=alert_data.labels,
        is_deduplicated=is_dup,
        status=AlertStatus.DEDUPLICATED if is_dup else AlertStatus.ACTIVE,
    )

    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    # Step 3 — route if not a duplicate
    if not is_dup:
        await route_alert(alert, db)

    return alert


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/prometheus")
async def ingest_prometheus(
    webhook: PrometheusWebhook,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """
    Accepts Prometheus Alertmanager webhook format.
    One webhook call can contain multiple alerts.
    """
    alerts = normalize_prometheus(webhook)

    if not alerts:
        return {"received": 0, "results": []}

    results = []
    for alert_data in alerts:
        alert = await process_alert(alert_data, db)
        results.append({
            "id": str(alert.id),
            "title": alert.title,
            "severity": alert.severity.value,
            "service": alert.service,
            "deduplicated": alert.is_deduplicated,
            "routed_to": alert.routed_to,
            "status": alert.status.value,
        })

    return {
        "received": len(alerts),
        "results": results,
    }


@router.post("/pagerduty")
async def ingest_pagerduty(
    pd: PagerDutyAlert,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """
    Accepts PagerDuty Events API v2 webhook format.
    One webhook call contains one event.
    """
    alert_data = normalize_pagerduty(pd)
    alert = await process_alert(alert_data, db)

    return {
        "id": str(alert.id),
        "title": alert.title,
        "severity": alert.severity.value,
        "service": alert.service,
        "deduplicated": alert.is_deduplicated,
        "routed_to": alert.routed_to,
        "status": alert.status.value,
    }


@router.get("/health")
async def ingest_health():
    """Quick check that the ingestion service is up."""
    return {"status": "ok", "service": "ingest"}