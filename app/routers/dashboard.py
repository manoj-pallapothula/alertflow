from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.db.database import get_db
from app.models.alert import Alert, AlertStatus, Severity
from app.services.dedup import get_dedup_stats

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ─── Summary ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(db: AsyncSession = Depends(get_db)):
    """
    High level counts for the dashboard.
    Shows total alerts, breakdowns by status and severity,
    and how many fingerprints are currently in the dedup window.
    """

    # Total alerts ever received
    total = await db.scalar(
        select(func.count(Alert.id))
    )

    # Alerts currently active (not yet routed or resolved)
    active = await db.scalar(
        select(func.count(Alert.id)).where(
            Alert.status == AlertStatus.ACTIVE
        )
    )

    # Alerts that have been routed to a team
    routed = await db.scalar(
        select(func.count(Alert.id)).where(
            Alert.status == AlertStatus.ROUTED
        )
    )

    # Alerts that were duplicates and skipped
    deduplicated = await db.scalar(
        select(func.count(Alert.id)).where(
            Alert.is_deduplicated == True
        )
    )

    # Resolved alerts
    resolved = await db.scalar(
        select(func.count(Alert.id)).where(
            Alert.status == AlertStatus.RESOLVED
        )
    )

    # Count by severity
    by_severity = {}
    for sev in Severity:
        count = await db.scalar(
            select(func.count(Alert.id)).where(
                Alert.severity == sev
            )
        )
        by_severity[sev.value] = count

    # Count by service (top 10 noisiest services)
    service_result = await db.execute(
        select(Alert.service, func.count(Alert.id).label("count"))
        .group_by(Alert.service)
        .order_by(func.count(Alert.id).desc())
        .limit(10)
    )
    by_service = {row.service: row.count for row in service_result}

    # Redis dedup stats
    dedup_stats = await get_dedup_stats()

    return {
        "total_alerts": total,
        "by_status": {
            "active": active,
            "routed": routed,
            "deduplicated": deduplicated,
            "resolved": resolved,
        },
        "by_severity": by_severity,
        "by_service": by_service,
        "dedup": dedup_stats,
    }


# ─── Alert list ─────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    status: Optional[str] = Query(None, description="Filter by status: active, routed, deduplicated, resolved"),
    severity: Optional[str] = Query(None, description="Filter by severity: SEV1, SEV2, SEV3, SEV4"),
    service: Optional[str] = Query(None, description="Filter by service name"),
    team: Optional[str] = Query(None, description="Filter by team name"),
    limit: int = Query(50, ge=1, le=200, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db),
):
    """
    List alerts with optional filters.
    Supports filtering by status, severity, service, and team.
    Supports pagination via limit and offset.
    """

    query = select(Alert).order_by(Alert.created_at.desc())

    # Apply filters if provided
    if status:
        try:
            status_enum = AlertStatus(status)
            query = query.where(Alert.status == status_enum)
        except ValueError:
            pass

    if severity:
        try:
            severity_enum = Severity(severity)
            query = query.where(Alert.severity == severity_enum)
        except ValueError:
            pass

    if service:
        query = query.where(Alert.service.ilike(f"%{service}%"))

    if team:
        query = query.where(Alert.team.ilike(f"%{team}%"))

    # Apply pagination
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    alerts = result.scalars().all()

    return {
        "total_returned": len(alerts),
        "limit": limit,
        "offset": offset,
        "alerts": [
            {
                "id": str(a.id),
                "fingerprint": a.fingerprint,
                "source": a.source,
                "severity": a.severity.value,
                "service": a.service,
                "team": a.team,
                "title": a.title,
                "description": a.description,
                "status": a.status.value,
                "routed_to": a.routed_to,
                "is_deduplicated": a.is_deduplicated,
                "created_at": a.created_at.isoformat(),
                "updated_at": a.updated_at.isoformat(),
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            }
            for a in alerts
        ],
    }


# ─── Single alert ────────────────────────────────────────────────────────────

@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get full details of a single alert by ID.
    """
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Alert not found")

    return {
        "id": str(alert.id),
        "fingerprint": alert.fingerprint,
        "source": alert.source,
        "severity": alert.severity.value,
        "service": alert.service,
        "team": alert.team,
        "title": alert.title,
        "description": alert.description,
        "labels": alert.labels,
        "status": alert.status.value,
        "routed_to": alert.routed_to,
        "is_deduplicated": alert.is_deduplicated,
        "created_at": alert.created_at.isoformat(),
        "updated_at": alert.updated_at.isoformat(),
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
    }


# ─── Health ──────────────────────────────────────────────────────────────────

@router.get("/health")
async def dashboard_health():
    """Quick check that the dashboard service is up."""
    return {"status": "ok", "service": "dashboard"}