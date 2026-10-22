"""Assemble the live campaign monitoring board.

The board answers one question at a glance: *what is happening to every
recipient right now?*  It joins the per-recipient tracking row with the
append-only interaction ledger, derives the current funnel status, and computes
the number of seconds between each transition so the dashboard can show
"opened 9s after the email was sent" without trusting the browser clock.

Only the newest :data:`RECENT_EVENT_LIMIT` ledger entries are returned for the
ticker; the full history stays available through the dossier endpoints.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    TrainingInteraction,
)
from app.services.interaction_report import EVENT_LABELS

#: How many ledger rows the activity ticker receives.
RECENT_EVENT_LIMIT = 20

#: A recipient with activity inside this window is "active now".
ACTIVE_WINDOW_SECONDS = 300


def _aware(value: datetime | None) -> datetime | None:
    """Return a timezone-aware datetime (SQLite stores naive UTC values)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    """Return ``end - start`` in seconds, rounded to milliseconds."""
    start_aware, end_aware = _aware(start), _aware(end)
    if start_aware is None or end_aware is None:
        return None
    return round((end_aware - start_aware).total_seconds(), 3)


def _label(event_type: str | None) -> str | None:
    """Human label for a ledger event type."""
    if event_type is None:
        return None
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())


def _status(tracking: EmailTracking, *, launched: bool) -> str:
    """Derive the funnel status, keeping form views as their own stage."""
    if tracking.completed_training_at is not None:
        return "completed"
    if tracking.form_submitted_at is not None:
        return "submitted"
    if tracking.form_viewed_at is not None:
        return "form_viewed"
    if tracking.clicked_at is not None:
        return "clicked"
    if tracking.opened_at is not None:
        return "opened"
    if tracking.sent_at is not None:
        return "sent"
    return "failed" if launched else "pending"


def _fallback_last_event(tracking: EmailTracking) -> tuple[str | None, datetime | None]:
    """Pick the most recent transition when the ledger has no rows.

    Legacy tracking rows predate the interaction ledger.  Their timestamps are
    still authoritative, so the board reconstructs the last event from them
    instead of showing an empty card.
    """
    candidates = [
        ("training_completed", tracking.completed_training_at),
        ("form_submitted", tracking.form_submitted_at),
        ("phishing_reported", tracking.reported_at),
        ("form_viewed", tracking.form_viewed_at),
        ("link_clicked", tracking.clicked_at),
        ("email_opened", tracking.opened_at),
        ("email_delivered", tracking.delivered_at),
        ("email_sent", tracking.sent_at),
    ]
    reached = [(value, event_type) for event_type, value in candidates if value is not None]
    if not reached:
        return None, None
    value, event_type = max(reached, key=lambda item: _aware(item[0]))
    return event_type, value


class LiveBoardService:
    """Build the monitoring payload for one campaign."""

    async def build(self, campaign: EmailCampaign, db: AsyncSession) -> dict[str, Any]:
        """Return the live board for ``campaign``.

        Args:
            campaign: The campaign being monitored.
            db: Active session.

        Returns:
            A dict matching :class:`app.schemas.live.LiveBoard`.
        """
        now = datetime.now(timezone.utc)
        launched = campaign.launched_at is not None or campaign.status != "draft"

        rows = (
            await db.execute(
                select(EmailTracking, HumanAsset)
                .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .where(EmailTracking.campaign_id == campaign.id)
                .order_by(EmailTracking.created_at.asc())
            )
        ).all()

        interactions = (
            (
                await db.execute(
                    select(TrainingInteraction)
                    .where(TrainingInteraction.campaign_id == campaign.id)
                    .order_by(TrainingInteraction.occurred_at.asc())
                )
            )
            .scalars()
            .all()
        )

        names = {employee.id: employee.full_name for _, employee in rows}
        interaction_counts = Counter(item.tracking_id for item in interactions)
        last_interaction: dict[uuid.UUID, TrainingInteraction] = {}
        for item in interactions:
            last_interaction[item.tracking_id] = item

        template_name: str | None = None
        difficulty: int | None = None
        if campaign.template_id is not None:
            template = await db.get(EmailTemplate, campaign.template_id)
            if template is not None:
                template_name = template.name
                difficulty = template.difficulty_level

        recipients: list[dict[str, Any]] = []
        for tracking, employee in rows:
            status = _status(tracking, launched=launched)
            ledger_last = last_interaction.get(tracking.id)
            if ledger_last is not None:
                last_type = ledger_last.event_type
                last_at = _aware(ledger_last.occurred_at)
            else:
                last_type, last_at = _fallback_last_event(tracking)
            # Prefer the observed IP/device from the newest ledger event; fall back
            # to the denormalised tracking columns for legacy rows.
            last_ip = (
                ledger_last.ip_address
                if ledger_last is not None and ledger_last.ip_address
                else tracking.last_ip_address
            )
            last_user_agent = (
                ledger_last.user_agent
                if ledger_last is not None and ledger_last.user_agent
                else tracking.last_user_agent
            )

            recipients.append(
                {
                    "employee_id": employee.id,
                    "tracking_id": tracking.id,
                    "name": employee.full_name,
                    "email": employee.email,
                    "department": employee.department,
                    "job_title": employee.job_title,
                    "status": status,
                    "reported": tracking.reported_at is not None,
                    "sent_at": _aware(tracking.sent_at),
                    "delivered_at": _aware(tracking.delivered_at),
                    "opened_at": _aware(tracking.opened_at),
                    "clicked_at": _aware(tracking.clicked_at),
                    "form_viewed_at": _aware(tracking.form_viewed_at),
                    "submitted_at": _aware(tracking.form_submitted_at),
                    "reported_at": _aware(tracking.reported_at),
                    "completed_at": _aware(tracking.completed_training_at),
                    "open_count": tracking.open_count or 0,
                    "click_count": tracking.click_count or 0,
                    "submission_count": tracking.submission_count or 0,
                    "interactions_count": interaction_counts.get(tracking.id, 0),
                    "seconds_to_open": _seconds_between(tracking.sent_at, tracking.opened_at),
                    "seconds_to_click": _seconds_between(tracking.sent_at, tracking.clicked_at),
                    "seconds_to_form": _seconds_between(tracking.sent_at, tracking.form_viewed_at),
                    "seconds_to_submit": _seconds_between(
                        tracking.sent_at, tracking.form_submitted_at
                    ),
                    "last_event_at": last_at,
                    "last_event_type": last_type,
                    "last_event_label": _label(last_type),
                    "seconds_since_last_event": _seconds_between(last_at, now),
                    "last_ip_address": last_ip,
                    "last_user_agent": last_user_agent,
                    "immunity_score": float(employee.immunity_score)
                    if employee.immunity_score is not None
                    else None,
                    "behavioral_category": employee.behavioral_category,
                    "password_length": tracking.password_length,
                    "submitted_identifier": tracking.submitted_identifier,
                }
            )

        summary = self._summary(recipients, campaign)
        recent_events = [
            {
                "id": item.id,
                "employee_id": item.employee_id,
                "employee_name": names.get(item.employee_id, "Unknown recipient"),
                "event_type": item.event_type,
                "label": _label(item.event_type) or item.event_type,
                "occurred_at": _aware(item.occurred_at),
                "seconds_ago": _seconds_between(item.occurred_at, now) or 0.0,
                "ip_address": item.ip_address,
                "user_agent": item.user_agent,
            }
            for item in interactions[-RECENT_EVENT_LIMIT:][::-1]
        ]

        elapsed = (
            int((now - _aware(campaign.launched_at)).total_seconds())
            if campaign.launched_at is not None
            else None
        )
        return {
            "campaign": {
                "id": campaign.id,
                "name": campaign.name,
                "status": campaign.status,
                "template_name": template_name,
                "difficulty_level": difficulty,
                "total_targets": campaign.total_targets or len(recipients),
                "sent_count": campaign.sent_count or 0,
                "failed_count": campaign.failed_count or 0,
                "created_at": _aware(campaign.created_at),
                "launched_at": _aware(campaign.launched_at),
                "completed_at": _aware(campaign.completed_at),
                "elapsed_seconds": elapsed,
            },
            "summary": summary,
            "recipients": recipients,
            "recent_events": recent_events,
            "generated_at": now,
        }

    @staticmethod
    def _summary(
        recipients: list[dict[str, Any]], campaign: EmailCampaign
    ) -> dict[str, Any]:
        """Aggregate the recipient rows into funnel counters and averages."""
        total = campaign.total_targets or len(recipients)
        sent = sum(1 for row in recipients if row["sent_at"] is not None)
        delivered = sum(1 for row in recipients if row["delivered_at"] is not None)
        opened = sum(1 for row in recipients if row["opened_at"] is not None)
        clicked = sum(1 for row in recipients if row["clicked_at"] is not None)
        form_viewed = sum(1 for row in recipients if row["form_viewed_at"] is not None)
        submitted = sum(1 for row in recipients if row["submitted_at"] is not None)
        reported = sum(1 for row in recipients if row["reported"])
        completed = sum(1 for row in recipients if row["completed_at"] is not None)
        failed = max(campaign.failed_count or 0, sum(1 for row in recipients if row["status"] == "failed"))
        pending = max(total - sent - failed, 0)
        active = sum(
            1
            for row in recipients
            if row["seconds_since_last_event"] is not None
            and row["seconds_since_last_event"] <= ACTIVE_WINDOW_SECONDS
        )

        def average(key: str) -> float | None:
            values = [row[key] for row in recipients if row[key] is not None]
            return round(sum(values) / len(values), 3) if values else None

        def rate(count: int) -> float:
            return round(count / sent * 100, 2) if sent else 0.0

        return {
            "total": total,
            "sent": sent,
            "delivered": delivered,
            "opened": opened,
            "clicked": clicked,
            "form_viewed": form_viewed,
            "submitted": submitted,
            "reported": reported,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "active_last_5m": active,
            "open_rate": rate(opened),
            "click_rate": rate(clicked),
            "form_view_rate": rate(form_viewed),
            "submission_rate": rate(submitted),
            "completion_rate": rate(completed),
            "avg_seconds_to_open": average("seconds_to_open"),
            "avg_seconds_to_click": average("seconds_to_click"),
            "avg_seconds_to_submit": average("seconds_to_submit"),
        }
