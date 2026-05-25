import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.alert import (
    Alert, Severity, AlertStatus,
    PrometheusWebhook, PagerDutyAlert, AlertCreate
)
from app.services.dedup import check_and_mark_duplicate, clear_fingerprint
from app.services.routing import route_alert
from app.security import verify_api_key
from app.services import timeline as tl

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


# ─── Normalizers ─────────────────────────────────────────────────────────────

def normalize_prometheus(webhook: PrometheusWebhook) -> list[AlertCreate]:
    alerts = []
    for pa in webhook.alerts:
        labels = pa.labels
        fingerprint = hashlib.md5(
            json.dumps(labels, sort_keys=True).encode()
        ).hexdigest()
        severity_raw = labels.get("severity", "warning").lower()
        severity_map = {"critical": "SEV1", "warning": "SEV2", "info": "SEV3"}
        severity = severity_map.get(severity_raw, "SEV3")
        alerts.append(AlertCreate(
            fingerprint=fingerprint,
            source="prometheus",
            severity=severity,
            service=labels.get("job", labels.get("service", "unknown")),
            team=labels.get("team"),
            title=pa.annotations.get("summary", labels.get("alertname", "Unknown Alert")),
            description=pa.annotations.get("description"),
            labels=labels,
        ))
    return alerts


def normalize_pagerduty(pd: PagerDutyAlert) -> AlertCreate:
    payload = pd.payload
    severity_map = {"critical": "SEV1", "error": "SEV2", "warning": "SEV3", "info": "SEV4"}
    severity = severity_map.get(payload.get("severity", "warning"), "SEV3")
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


# ─── Core processing ──────────────────────────────────────────────────────────

async def process_alert(alert_data: AlertCreate, db: AsyncSession) -> Alert:
    """
    Core pipeline:
    1. Dedup check
    2. Save to database
    3. Record timeline event
    4. Route if not duplicate
    """
    is_dup = await check_and_mark_duplicate(alert_data.fingerprint)

    try:
        severity = Severity[alert_data.severity]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: {alert_data.severity}."
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

    # Record timeline event
    if is_dup:
        await tl.record_deduplicated(db, alert.id, alert_data.fingerprint)
    else:
        await tl.record_received(
            db, alert.id,
            alert_data.source,
            alert_data.severity,
            alert_data.service
        )

    if not is_dup:
        await route_alert(alert, db)

    return alert


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/health")
async def ingest_health():
    return {"status": "ok", "service": "ingest"}


@router.post("/prometheus")
async def ingest_prometheus(
    webhook: PrometheusWebhook,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
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

    return {"received": len(alerts), "results": results}


@router.post("/pagerduty")
async def ingest_pagerduty(
    pd: PagerDutyAlert,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
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


@router.post("/prometheus/resolve")
async def resolve_prometheus(
    webhook: PrometheusWebhook,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    resolved = []
    not_found = []

    for pa in webhook.alerts:
        if not pa.endsAt:
            continue
        try:
            ends_at = datetime.fromisoformat(pa.endsAt.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ends_at > datetime.now(timezone.utc):
            continue

        labels = pa.labels
        fingerprint = hashlib.md5(
            json.dumps(labels, sort_keys=True).encode()
        ).hexdigest()

        result = await db.execute(
            select(Alert)
            .where(Alert.fingerprint == fingerprint)
            .where(Alert.status != AlertStatus.RESOLVED)
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        alert = result.scalar_one_or_none()

        if alert:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.utcnow()
            await db.commit()
            await clear_fingerprint(fingerprint)
            await tl.record_resolved(db, alert.id)

            resolved.append({
                "id": str(alert.id),
                "fingerprint": fingerprint,
                "service": alert.service,
                "title": alert.title,
                "resolved_at": alert.resolved_at.isoformat(),
            })
        else:
            not_found.append(fingerprint)

    return {
        "resolved": len(resolved),
        "not_found": len(not_found),
        "alerts": resolved,
    }