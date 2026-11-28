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
    if tracking.is_reported_safe:
        return "reported_safe"
    if tracking.delivery_status == "no_answer":
        # A real voice call that rang without pickup is an employee outcome, not
        # a delivery error; show it apart from provider failures.
        return "no_answer"
    if tracking.completed_at is not None:
        return "completed"
    if tracking.submitted_at is not None:
        return "submitted"
    if tracking.viewed_at is not None:
        return "form_viewed"
    if tracking.clicked_at is not None:
        return "clicked"
    if tracking.opened_at is not None:
        return "opened"
    if tracking.sent_at is not None:
        return "sent"
    return "failed" if launched else "pending"


def _telemetry_fields(tracking: EmailTracking) -> dict[str, Any]:
    """Extract the display fields of the endpoint profile a USB document sent.

    The full packet lives in ``client_context['usb_telemetry']``; the board only
    needs the forensic headline: which machine, which screen and GPU, how good
    the connection was, where it came from and which file path was opened.  A
    document that could not reach the server (offline open) leaves these empty,
    and the card falls back to IP/User-Agent from the tracking row.
    """
    context = tracking.client_context if isinstance(tracking.client_context, dict) else {}
    packet = context.get("usb_telemetry")
    packet = packet if isinstance(packet, dict) else {}
    device = packet.get("device") if isinstance(packet.get("device"), dict) else {}
    screen = packet.get("screen") if isinstance(packet.get("screen"), dict) else {}
    network = packet.get("network") if isinstance(packet.get("network"), dict) else {}
    gpu = packet.get("gpu") if isinstance(packet.get("gpu"), dict) else {}
    source = packet.get("source") if isinstance(packet.get("source"), dict) else {}
    server = packet.get("server") if isinstance(packet.get("server"), dict) else {}
    geo = context.get("geo") if isinstance(context.get("geo"), dict) else {}

    platform = device.get("ua_platform") or device.get("platform")
    platform_version = device.get("ua_platform_version")
    browser = device.get("browser")
    os_name = device.get("os")
    headline = " ".join(
        str(part)
        for part in (os_name or platform, platform_version if not os_name else None, browser)
        if part
    ).strip()
    details: list[str] = []
    if screen.get("width") and screen.get("height"):
        details.append(f"{screen['width']}x{screen['height']}")
    if screen.get("pixel_ratio"):
        details.append(f"@{screen['pixel_ratio']}x")
    if device.get("hardware_concurrency"):
        details.append(f"{device['hardware_concurrency']} CPU")
    if device.get("device_memory_gb"):
        details.append(f"{device['device_memory_gb']} GB RAM")
    if gpu.get("renderer"):
        details.append(str(gpu["renderer"])[:70])
    summary = " · ".join(part for part in (headline, " · ".join(details)) if part) or None

    location_parts = [
        str(value)
        for value in (
            server.get("city") or geo.get("city"),
            server.get("country") or geo.get("country"),
            server.get("isp") or geo.get("isp"),
        )
        if value
    ]
    connection = network.get("effective_type")
    if connection:
        location_parts.append(f"{connection} link")

    return {
        "device_summary": summary,
        "device_platform": os_name or platform,
        "device_browser": browser,
        "device_model": server.get("device_model"),
        "device_screen": (
            f"{screen.get('width')}x{screen.get('height')}"
            if screen.get("width") and screen.get("height")
            else None
        ),
        "device_gpu": gpu.get("renderer"),
        "device_cpu_cores": device.get("hardware_concurrency"),
        "device_memory_gb": device.get("device_memory_gb"),
        "device_timezone": device.get("timezone"),
        "device_language": device.get("language"),
        "device_battery": packet.get("power") or packet.get("battery") or None,
        "device_network": network or None,
        "device_local_ips": (packet.get("webrtc") or {}).get("local_ips") or None,
        "device_fingerprint": packet.get("fingerprint"),
        "device_hostname": device.get("hostname") or context.get("hostname"),
        "device_username": device.get("username") or context.get("username"),
        "geo_label": " · ".join(location_parts) or None,
        "geo_city": server.get("city") or geo.get("city"),
        "geo_country": server.get("country") or geo.get("country"),
        "geo_isp": server.get("isp") or geo.get("isp"),
        "geo_latitude": server.get("latitude") if server.get("latitude") is not None else geo.get("latitude"),
        "geo_longitude": server.get("longitude") if server.get("longitude") is not None else geo.get("longitude"),
        "source_path": source.get("path") or context.get("source_path"),
        "opened_from": "usb" if tracking.channel == "usb" else None,
        "telemetry_received": bool(packet),
    }


def _fallback_last_event(tracking: EmailTracking) -> tuple[str | None, datetime | None]:
    """Pick the most recent transition when the ledger has no rows.

    Legacy tracking rows predate the interaction ledger.  Their timestamps are
    still authoritative, so the board reconstructs the last event from them
    instead of showing an empty card.
    """
    candidates = [
        ("training_completed", tracking.completed_at),
        ("form_submitted", tracking.submitted_at),
        ("phishing_reported", tracking.reported_at),
        ("form_viewed", tracking.viewed_at),
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
                .outerjoin(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
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

        names = {employee.id: employee.full_name for _, employee in rows if employee is not None}
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

            telemetry = _telemetry_fields(tracking)
            is_usb = (tracking.channel or "").strip().lower() == "usb"
            generic_label = "USB drop endpoint" if is_usb else "Unknown QR Visitor"

            emp_id = employee.id if employee is not None else tracking.id
            emp_name = (
                employee.full_name
                if employee is not None
                else (
                    telemetry.get("device_hostname")
                    or telemetry.get("device_username")
                    or tracking.submitted_username
                    or tracking.submitted_email
                    or generic_label
                )
            )
            emp_email = employee.email if employee is not None else (tracking.submitted_email or "—")
            emp_dept = (
                employee.department
                if employee is not None
                else ("Physical USB drop" if is_usb else "QR Capture")
            )
            emp_job = (
                employee.job_title
                if employee is not None
                else (telemetry.get("device_summary") or "Unidentified endpoint")
            )
            immunity = float(employee.immunity_score) if (employee is not None and employee.immunity_score is not None) else None
            behavioral_cat = employee.behavioral_category if employee is not None else "unaware"

            recipients.append(
                {
                    "employee_id": emp_id,
                    "tracking_id": tracking.id,
                    "name": emp_name,
                    "email": emp_email,
                    "department": emp_dept,
                    "job_title": emp_job,
                    "status": status,
                    "reported": bool(tracking.is_reported_safe)
                    or tracking.reported_at is not None,
                    "sent_at": _aware(tracking.sent_at),
                    "delivered_at": _aware(tracking.delivered_at),
                    "opened_at": _aware(tracking.opened_at),
                    "clicked_at": _aware(tracking.clicked_at),
                    "form_viewed_at": _aware(tracking.viewed_at),
                    "submitted_at": _aware(tracking.submitted_at),
                    "reported_at": _aware(tracking.reported_at),
                    "completed_at": _aware(tracking.completed_at),
                    "quiz_score": tracking.quiz_score,
                    "quiz_total": tracking.quiz_total,
                    "is_reported_safe": bool(tracking.is_reported_safe),
                    "open_count": tracking.open_count or 0,
                    "click_count": tracking.click_count or 0,
                    "submission_count": tracking.submission_count or 0,
                    "interactions_count": interaction_counts.get(tracking.id, 0),
                    "seconds_to_open": _seconds_between(tracking.sent_at, tracking.opened_at),
                    "seconds_to_click": _seconds_between(tracking.sent_at, tracking.clicked_at),
                    "seconds_to_form": _seconds_between(tracking.sent_at, tracking.viewed_at),
                    "seconds_to_submit": _seconds_between(
                        tracking.sent_at, tracking.submitted_at
                    ),
                    "last_event_at": last_at,
                    "last_event_type": last_type,
                    "last_event_label": _label(last_type),
                    "seconds_since_last_event": _seconds_between(last_at, now),
                    "last_ip_address": last_ip,
                    "last_user_agent": last_user_agent,
                    "immunity_score": immunity,
                    "behavioral_category": behavioral_cat,
                    "password_length": tracking.password_length,
                    "submitted_identifier": tracking.submitted_identifier,
                    **telemetry,
                }
            )

        summary = self._summary(recipients, campaign)
        recent_events = [
            {
                "id": item.id,
                "employee_id": item.employee_id,
                "employee_name": names.get(item.employee_id)
                or (item.details or {}).get("hostname")
                or ("USB drop endpoint" if (item.details or {}).get("channel") == "usb" else "Unattributed endpoint"),
                "device": (item.details or {}).get("device"),
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
                "channel": campaign.channel or "email",
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
