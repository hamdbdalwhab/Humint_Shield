"""Smart alerting rules for the live monitoring dashboard.

The rules are intentionally few and deterministic: an alert that fires on
noise gets ignored, so each one describes an actionable, already-measured
condition rather than a guess.

Rules implemented:

``critical_risk``
    An active employee's Elo fell below the critical threshold.
``mass_clicks``
    An active campaign shows a click rate high enough to mean the lure fooled a
    meaningful share of recipients (at least 30% of sends, with a floor of 3).
``stalled_campaign``
    An active campaign launched more than 24 hours ago has recorded no opens,
    which usually means delivery or tracking is broken.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, HumanAsset

#: Elo at or below which an employee is reported as critical risk.
CRITICAL_ELO_THRESHOLD = 600
#: Minimum sends before a campaign click rate is meaningful.
MASS_CLICK_MIN_SENDS = 5
#: Click-rate share that triggers the mass-click alert.
MASS_CLICK_RATE = 0.30
#: Hours after launch with zero opens before a campaign is considered stalled.
STALLED_AFTER_HOURS = 24


async def collect_smart_alerts(
    db: AsyncSession, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Evaluate every alert rule against the current database state.

    Args:
        db: Active session.
        now: Evaluation timestamp (defaults to the current UTC time); injectable
            so the rules can be tested deterministically.

    Returns:
        A list of alert dictionaries with ``type``, ``severity``, ``title_ar``,
        ``detail_ar``, ``entity_id`` and the measurements behind the alert.
    """
    reference = now or datetime.now(timezone.utc)
    alerts: list[dict[str, Any]] = []

    critical = (
        await db.execute(
            select(HumanAsset)
            .where(
                HumanAsset.is_active.is_(True),
                HumanAsset.elo_score <= CRITICAL_ELO_THRESHOLD,
            )
            .order_by(HumanAsset.elo_score.asc())
            .limit(50)
        )
    ).scalars().all()
    if critical:
        alerts.append(
            {
                "type": "critical_risk",
                "severity": "critical",
                "title_ar": "موظفون في نطاق الخطر الحرج",
                "detail_ar": (
                    f"{len(critical)} موظفاً نشطاً تحت درجة Elo "
                    f"{CRITICAL_ELO_THRESHOLD}: "
                    + "، ".join(
                        f"{employee.full_name} ({int(employee.elo_score)})"
                        for employee in critical[:10]
                    )
                ),
                "entity_id": None,
                "measurements": {
                    "count": len(critical),
                    "threshold": CRITICAL_ELO_THRESHOLD,
                    "employee_ids": [str(employee.id) for employee in critical],
                },
            }
        )

    active_campaigns = (
        await db.execute(
            select(EmailCampaign).where(EmailCampaign.status == "active")
        )
    ).scalars().all()
    mass_clicked: list[EmailCampaign] = []
    stalled: list[EmailCampaign] = []
    for campaign in active_campaigns:
        sent = int(campaign.sent_count or 0)
        clicked = int(campaign.clicked_count or 0)
        if (
            sent >= MASS_CLICK_MIN_SENDS
            and clicked >= 3
            and clicked / sent >= MASS_CLICK_RATE
        ):
            mass_clicked.append(campaign)
        launched_at = campaign.launched_at
        if launched_at is not None:
            if launched_at.tzinfo is None:
                launched_at = launched_at.replace(tzinfo=timezone.utc)
            if (
                reference - launched_at >= timedelta(hours=STALLED_AFTER_HOURS)
                and int(campaign.opened_count or 0) == 0
            ):
                stalled.append(campaign)

    if mass_clicked:
        alerts.append(
            {
                "type": "mass_clicks",
                "severity": "high",
                "title_ar": "نقرات جماعية على حملة نشطة",
                "detail_ar": "، ".join(
                    f"{campaign.name} ({campaign.clicked_count}/{campaign.sent_count} نقر)"
                    for campaign in mass_clicked[:10]
                ),
                "entity_id": str(mass_clicked[0].id),
                "measurements": {
                    "campaigns": [
                        {
                            "campaign_id": str(campaign.id),
                            "sent": int(campaign.sent_count or 0),
                            "clicked": int(campaign.clicked_count or 0),
                            "rate": round(
                                int(campaign.clicked_count or 0)
                                / max(1, int(campaign.sent_count or 0)),
                                3,
                            ),
                        }
                        for campaign in mass_clicked
                    ],
                    "threshold": MASS_CLICK_RATE,
                },
            }
        )

    if stalled:
        alerts.append(
            {
                "type": "stalled_campaign",
                "severity": "warning",
                "title_ar": "حملة نشطة بلا أي فتح",
                "detail_ar": "، ".join(campaign.name for campaign in stalled[:10]),
                "entity_id": str(stalled[0].id),
                "measurements": {
                    "campaign_ids": [str(campaign.id) for campaign in stalled],
                    "hours": STALLED_AFTER_HOURS,
                },
            }
        )

    return alerts


__all__ = [
    "CRITICAL_ELO_THRESHOLD",
    "MASS_CLICK_MIN_SENDS",
    "MASS_CLICK_RATE",
    "STALLED_AFTER_HOURS",
    "collect_smart_alerts",
]
