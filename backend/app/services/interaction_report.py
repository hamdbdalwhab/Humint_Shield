"""Read-side assembly of the per-employee / per-campaign interaction dossier.

The data lives in three places: the per-recipient ``email_tracking`` row (the
current funnel state), the append-only ``training_interactions`` ledger (every
event with microsecond timestamps) and the encrypted payload columns (exactly
what the recipient typed).

This service merges them into one shape used by:

* ``GET /employees/{id}/dossier``                — the employee's full profile
* ``GET /email-campaigns/{id}/recipients/{eid}``  — one recipient in a campaign
* ``GET /email-campaigns/{id}/activity``          — the campaign audit feed

Legacy tracking rows created before the ledger existed are supported: when a
row has no ledger entries, the timestamps already on the row are turned into a
synthetic event list so history is never lost.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset, TrainingInteraction
from app.services.tracking_service import decrypt_payload, latest_submitted_values

#: Human labels for the ledger event types.
EVENT_LABELS = {
    "campaign_assigned": "Campaign assigned",
    "email_sent": "Email accepted by the mail server",
    "email_delivered": "Email delivered",
    "message_sent": "Message accepted by the provider",
    "message_delivered": "Message delivered",
    "message_read": "Message read",
    "email_open": "Email opened",
    "email_opened": "Email opened",
    "link_click": "Link clicked",
    "link_clicked": "Link clicked",
    "form_viewed": "Training form displayed",
    "training_form_viewed": "Training form displayed",
    "form_submitted": "Credentials entered",
    "credentials_submitted": "Credentials entered",
    "phishing_reported": "Reported as phishing",
    "reported_phish": "Reported as phishing",
    "training_completed": "Micro-training completed",
    "qr_scanned": "QR code scanned",
    "usb_opened": "USB awareness document opened",
    "usb_device_probe": "Device identity collected by the local tool",
    "credential_disclosed": "Verification code disclosed",
    "financial_fraud": "Gift-card codes sent",
    # Real voice calls.  ``not_answered`` is a recipient outcome (the phone rang
    # and nobody picked up); ``failed`` means the call never got through.
    "vishing_call_placed": "Vishing call placed",
    "vishing_call_created": "Vishing call placed",
    "vishing_call_ringing": "Phone ringing",
    "vishing_call_answered": "Call answered",
    "vishing_call_completed": "Vishing call completed",
    "vishing_call_not_answered": "Vishing call — no answer",
    "vishing_call_failed": "Vishing call could not be completed",
}


def _event(
    event_type: str,
    occurred_at,
    details: dict | None,
    *,
    values: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """Build one interaction dict in the API shape."""
    return {
        "id": uuid.uuid4(),
        "event_type": event_type,
        "occurred_at": occurred_at,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "details": details or {},
        "values": values,
    }


def synthesized_events(tracking: EmailTracking) -> list[dict]:
    """Reconstruct an event list for a row created before the ledger existed.

    Args:
        tracking: The tracking row.

    Returns:
        Events ordered oldest first, derived from the row's timestamps.
    """
    assigned_at = tracking.created_at
    if (
        assigned_at is not None
        and tracking.sent_at is not None
        and assigned_at > tracking.sent_at
    ):
        # ``created_at`` is applied at flush time; never let it sort after the
        # send it precedes.
        assigned_at = tracking.sent_at
    events: list[dict] = [
        _event("campaign_assigned", assigned_at, {}),
    ]
    if tracking.sent_at is not None:
        events.append(
            _event(
                "message_sent" if (tracking.channel or "email") != "email" else "email_sent",
                tracking.sent_at,
                {"message_id": tracking.provider_message_id, "synthetic": True},
            )
        )
    if tracking.delivered_at is not None:
        events.append(
            _event(
                "message_delivered"
                if (tracking.channel or "email") != "email"
                else "email_delivered",
                tracking.delivered_at,
                {"synthetic": True},
            )
        )
    if tracking.read_at is not None:
        events.append(
            _event(
                "message_read",
                tracking.read_at,
                {"synthetic": True},
            )
        )
    if tracking.opened_at is not None:
        events.append(
            _event(
                "email_opened",
                tracking.opened_at,
                {"open_count": tracking.open_count, "synthetic": True},
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
            )
        )
    if tracking.clicked_at is not None:
        events.append(
            _event(
                "link_clicked",
                tracking.clicked_at,
                {"click_count": tracking.click_count, "synthetic": True},
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
            )
        )
    if tracking.viewed_at is not None:
        events.append(
            _event(
                "training_form_viewed",
                tracking.viewed_at,
                {"synthetic": True},
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
            )
        )
    if tracking.submitted_at is not None:
        legacy_values = decrypt_payload(tracking.submitted_payload_encrypted)
        if not legacy_values:
            legacy_values = dict(tracking.submitted_fields or {})
            if tracking.submitted_identifier:
                legacy_values.setdefault("identifier", tracking.submitted_identifier)
        events.append(
            _event(
                "credentials_submitted",
                tracking.submitted_at,
                {
                    "submission_count": tracking.submission_count,
                    "password_length": tracking.password_length,
                    "synthetic": True,
                },
                values=legacy_values,
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
            )
        )
    if tracking.reported_at is not None:
        events.append(
            _event(
                "phishing_reported",
                tracking.reported_at,
                {
                    "source": (
                        "admin_report_safe"
                        if tracking.is_reported_safe
                        else "training_page"
                    ),
                    "quiz_score": tracking.quiz_score,
                    "quiz_total": tracking.quiz_total,
                    "synthetic": True,
                },
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
            )
        )
    if tracking.completed_at is not None:
        events.append(
            _event(
                "training_completed",
                tracking.completed_at,
                {
                    "quiz_score": tracking.quiz_score,
                    "quiz_total": tracking.quiz_total,
                    "synthetic": True,
                },
            )
        )
    events.sort(key=lambda item: item["occurred_at"])
    return events


def serialize_interaction(interaction: TrainingInteraction) -> dict:
    """Convert a ledger row into the API shape, decrypting its payload."""
    values = decrypt_payload(interaction.payload_encrypted) or None
    if values is None and interaction.event_type == "form_submitted":
        values = {}
    return {
        "id": interaction.id,
        "event_type": interaction.event_type,
        "occurred_at": interaction.occurred_at,
        "ip_address": interaction.ip_address,
        "user_agent": interaction.user_agent,
        "details": interaction.details or {},
        "values": values,
    }


def build_forensic_context(tracking: EmailTracking) -> dict | None:
    """Flatten what a USB document captured into the dossier's field names.

    The packet is stored nested (``client_context['usb_telemetry']`` with
    ``device``/``screen``/``gpu``/``webrtc``/``server`` sub-objects) so nothing
    is lost.  The dossier renders one flat card per section, so this helper
    lifts every value to the key the UI reads **and** keeps the raw packet, so a
    scan is never displayed as a wall of dashes.

    Returns:
        The flattened context, or ``None`` when the tracking row never carried
        a client context (email/SMS rows).
    """
    raw = tracking.client_context
    context = raw if isinstance(raw, dict) else {}
    if not context:
        return None
    packet = (
        context.get("usb_telemetry")
        if isinstance(context.get("usb_telemetry"), dict)
        else {}
    )
    if not packet:
        # Email/QR contexts are already flat; flattening them with an empty USB
        # packet would overwrite their own keys with ``None``.
        return context
    device = packet.get("device") if isinstance(packet.get("device"), dict) else {}
    screen = packet.get("screen") if isinstance(packet.get("screen"), dict) else {}
    gpu = packet.get("gpu") if isinstance(packet.get("gpu"), dict) else {}
    source = packet.get("source") if isinstance(packet.get("source"), dict) else {}
    server = packet.get("server") if isinstance(packet.get("server"), dict) else {}
    webrtc = packet.get("webrtc") if isinstance(packet.get("webrtc"), dict) else {}
    network = packet.get("network") if isinstance(packet.get("network"), dict) else {}
    geo = context.get("geo") if isinstance(context.get("geo"), dict) else {}
    probe_block = (
        packet.get("local_probe")
        if isinstance(packet.get("local_probe"), dict)
        else {}
    )
    # The optional local collector is the only source that can name the Windows
    # account and the real machine; when it ran, its values outrank the browser's
    # masked guesses.  ``identity`` is the current shape; the block itself is
    # accepted too so an older row still renders.
    probe = (
        probe_block.get("identity")
        if isinstance(probe_block.get("identity"), dict)
        else probe_block
    )
    source_meta = (
        context.get("usb_source")
        if isinstance(context.get("usb_source"), dict)
        else {}
    )

    candidates = [str(item) for item in (webrtc.get("local_ips") or []) if item]
    mdns_name = next((item for item in candidates if item.endswith(".local")), None)
    # Modern browsers replace the real hostname with a random mDNS UUID.  It is
    # kept (it still identifies the machine across visits) but it must never be
    # presented as the machine's name.
    random_mdns = bool(
        mdns_name
        and re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.local",
            mdns_name,
        )
    )
    browser_hostname = device.get("hostname") or context.get("hostname")
    probe_hostname = probe.get("hostname") or None
    probe_username = probe.get("username") or None
    device_real_name = (
        probe_hostname
        or (None if (browser_hostname and random_mdns) else browser_hostname)
        or context.get("device_real_name")
        or None
    )
    identity_source = context.get("identity_source") or (
        "local_tool"
        if probe
        else "query_parameter"
        if context.get("username") or context.get("hostname")
        else None
    )
    local_ip = next((item for item in candidates if not item.endswith(".local")), None)
    fingerprint_value = (
        packet.get("fingerprint")
        or context.get("device_fingerprint")
        or None
    )
    scan_count = int(tracking.open_count or 1)

    return {
        **context,
        # --- Hardware ---------------------------------------------------
        "device_real_name": device_real_name,
        "device_model": (
            probe.get("model") or server.get("device_model") or device.get("ua_model") or None
        ),
        "device_owner_name": context.get("device_owner_name") or None,
        "gpu_renderer": gpu.get("renderer") or None,
        "gpu_vendor": gpu.get("vendor") or None,
        "webgl_renderer": gpu.get("renderer") or None,
        "cpu_cores": probe.get("cpu_cores") or device.get("hardware_concurrency") or None,
        "cpu_model": probe.get("cpu") or None,
        "cpu_logical": probe.get("cpu_logical") or None,
        "device_memory_gb": (
            probe.get("ram_gb")
            or device.get("device_memory_gb")
            or device.get("estimate_ram_gb")
            or None
        ),
        "hardware_fingerprint": fingerprint_value,
        "fingerprint_hash": fingerprint_value,
        # --- Network ----------------------------------------------------
        "local_ip": local_ip or tracking.last_ip_address,
        "public_ip": server.get("ip") or tracking.last_ip_address,
        "mDNS_name": mdns_name,
        "hostname": probe_hostname or (None if random_mdns else browser_hostname or None),
        "username": probe_username or device.get("username") or context.get("username") or None,
        # --- Local identity tool ---------------------------------------
        "identity_source": identity_source,
        "windows_account": probe_username,
        "windows_hostname": probe_hostname,
        "windows_account_domain": probe.get("user_domain") or probe.get("domain"),
        "windows_logged_on_user": probe.get("logged_on_user") or None,
        "device_domain": probe.get("domain") or probe.get("workgroup") or None,
        "device_manufacturer": probe.get("manufacturer") or None,
        "device_serial": probe.get("serial") or None,
        "os_build": probe.get("os_build") or None,
        "os_version": probe.get("os_version") or None,
        "probe_elevated": probe.get("is_admin"),
        "probe_collected_at": probe.get("collected_at") or probe_block.get("received_at"),
        "probe_mac": probe.get("mac") or None,
        "local_probe": probe_block or None,
        "isp": server.get("isp") or geo.get("isp") or None,
        "city": server.get("city") or geo.get("city") or None,
        "country": server.get("country") or geo.get("country") or None,
        "latitude": (
            server.get("latitude")
            if server.get("latitude") is not None
            else geo.get("latitude")
        ),
        "longitude": (
            server.get("longitude")
            if server.get("longitude") is not None
            else geo.get("longitude")
        ),
        # --- Display & browser -----------------------------------------
        "screen_resolution": (
            f"{screen.get('width')}x{screen.get('height')}"
            if screen.get("width") and screen.get("height")
            else None
        ),
        "pixel_ratio": screen.get("pixel_ratio"),
        "color_depth": screen.get("color_depth"),
        "language": device.get("language") or context.get("language"),
        "languages": device.get("languages") or context.get("languages"),
        "timezone": device.get("timezone") or context.get("timezone"),
        "os": device.get("os") or context.get("os"),
        "browser": device.get("browser") or context.get("browser"),
        "user_agent": (
            device.get("user_agent")
            or tracking.last_user_agent
            or context.get("user_agent")
        ),
        "network": network or None,
        "power": packet.get("power") or None,
        # --- Provenance ------------------------------------------------
        "status": context.get("status") or (
            "repeat_scan" if scan_count > 1 else "first_scan"
        ),
        "scan_count": scan_count,
        "source_path": (
            source.get("path") or context.get("source_path") or source_meta.get("path")
        ),
        "source_url": source.get("href") or source_meta.get("href"),
        "opened_at": source.get("opened_at"),
        "telemetry_received": bool(packet),
        # Raw packets stay available for the debug footer and exports.
        "usb_telemetry": packet or None,
        "geo": geo or None,
    }


def build_record(
    tracking: EmailTracking,
    campaign: EmailCampaign,
    template: EmailTemplate | None,
    events: list[dict],
) -> dict:
    """Build the ``EmployeeCampaignRecord`` dict for one tracking row.

    Args:
        tracking: The recipient's tracking row.
        campaign: The campaign it belongs to.
        template: The template used, when it still exists.
        events: Serialized ledger events (oldest first).

    Returns:
        A mapping ready for ``EmployeeCampaignRecord``.
    """
    submissions = [
        {
            "occurred_at": event["occurred_at"],
            "ip_address": event["ip_address"],
            "user_agent": event["user_agent"],
            "password_length": (event["details"] or {}).get("password_length"),
            "client": (event["details"] or {}).get("client") or None,
            "values": event["values"] or {},
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
        }
        for event in events
        if event["event_type"] in ("form_submitted", "credentials_submitted")
    ]
    latest_values = submissions[-1]["values"] if submissions else None
    if latest_values is None:
        latest_values = latest_submitted_values(tracking)

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_status": campaign.status,
        "template_name": template.name if template is not None else None,
        "channel": tracking.channel or campaign.channel or "email",
        "tracking_uuid": tracking.tracking_uuid,
        "status": tracking.status,
        "sent_at": tracking.sent_at,
        "delivered_at": tracking.delivered_at,
        "delivery_status": tracking.delivery_status,
        "delivery_error": tracking.delivery_error,
        "read_at": tracking.read_at,
        "provider_message_id": tracking.provider_message_id,
        "opened_at": tracking.opened_at,
        "clicked_at": tracking.clicked_at,
        "form_viewed_at": tracking.viewed_at,
        "submitted_at": tracking.submitted_at,
        "reported_at": tracking.reported_at,
        "completed_at": tracking.completed_at,
        "quiz_score": tracking.quiz_score,
        "quiz_total": tracking.quiz_total,
        "is_reported_safe": bool(tracking.is_reported_safe),
        "open_count": tracking.open_count or 0,
        "click_count": tracking.click_count or 0,
        "submission_count": tracking.submission_count or 0,
        "submitted_identifier": tracking.submitted_identifier,
        "submitted_fields": tracking.submitted_fields or None,
        "submitted_values": latest_values,
        "client_context": build_forensic_context(tracking),
        "events": events,
        "submissions": submissions,
    }


class InteractionReportService:
    """Assembles dossiers from tracking rows, the ledger and encrypted payloads."""

    async def _events_for(
        self, tracking_ids: list[uuid.UUID], db: AsyncSession
    ) -> dict[uuid.UUID, list[dict]]:
        """Load and group ledger events for a set of tracking rows."""
        if not tracking_ids:
            return {}
        rows = (
            await db.execute(
                select(TrainingInteraction)
                .where(TrainingInteraction.tracking_id.in_(tracking_ids))
                .order_by(TrainingInteraction.occurred_at.asc())
            )
        ).scalars().all()
        grouped: dict[uuid.UUID, list[dict]] = {}
        for interaction in rows:
            grouped.setdefault(interaction.tracking_id, []).append(
                serialize_interaction(interaction)
            )
        return grouped

    async def employee_dossier(
        self, employee: HumanAsset, db: AsyncSession
    ) -> dict[str, Any]:
        """Build the complete dossier for one employee.

        Args:
            employee: The employee (already access-checked).
            db: Active session.

        Returns:
            ``{"employee", "summary", "campaigns", "events", "submissions"}``.
        """
        rows = (
            await db.execute(
                select(EmailTracking, EmailCampaign, EmailTemplate)
                .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
                .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
                .where(EmailTracking.employee_id == employee.id)
                .order_by(EmailTracking.created_at.asc())
            )
        ).all()

        grouped = await self._events_for([row[0].id for row in rows], db)

        campaigns: list[dict] = []
        all_events: list[dict] = []
        all_submissions: list[dict] = []
        for tracking, campaign, template in rows:
            events = grouped.get(tracking.id) or synthesized_events(tracking)
            record = build_record(tracking, campaign, template, events)
            campaigns.append(record)
            # The merged timeline mixes campaigns, so every event carries the
            # campaign it belongs to.
            all_events.extend(
                {
                    **event,
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                }
                for event in events
            )
            all_submissions.extend(record["submissions"])

        all_events.sort(key=lambda item: item["occurred_at"])
        all_submissions.sort(key=lambda item: item["occurred_at"])

        timestamps = [event["occurred_at"] for event in all_events]
        summary = {
            "campaigns": len(campaigns),
            "emails_sent": sum(1 for item in campaigns if item["sent_at"] is not None),
            "opened": sum(1 for item in campaigns if item["opened_at"] is not None),
            "clicked": sum(1 for item in campaigns if item["clicked_at"] is not None),
            "submitted": sum(1 for item in campaigns if item["submitted_at"] is not None),
            "reported": sum(1 for item in campaigns if item["reported_at"] is not None),
            "completed": sum(1 for item in campaigns if item["completed_at"] is not None),
            "total_interactions": len(all_events),
            "first_interaction_at": min(timestamps) if timestamps else None,
            "last_interaction_at": max(timestamps) if timestamps else None,
        }
        return {
            "employee": employee,
            "summary": summary,
            "campaigns": campaigns,
            "events": all_events,
            "submissions": all_submissions,
        }

    async def campaign_recipient(
        self,
        campaign: EmailCampaign,
        employee: HumanAsset,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Build one recipient's record inside one campaign.

        Args:
            campaign: The campaign.
            employee: The recipient.
            db: Active session.

        Returns:
            ``{"campaign", "employee", "record"}``.

        Raises:
            LookupError: When the employee has no tracking row in the campaign.
        """
        row = (
            await db.execute(
                select(EmailTracking, EmailTemplate)
                .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
                .where(
                    EmailTracking.campaign_id == campaign.id,
                    or_(
                        EmailTracking.employee_id == employee.id,
                        EmailTracking.id == employee.id,
                    ),
                )
            )
        ).first()
        if row is None:
            raise LookupError("recipient not part of this campaign")
        tracking, template = row
        grouped = await self._events_for([tracking.id], db)
        events = grouped.get(tracking.id) or synthesized_events(tracking)
        return {
            "campaign": campaign,
            "employee": employee,
            "record": build_record(tracking, campaign, template, events),
        }

    async def campaign_activity(
        self, campaign: EmailCampaign, db: AsyncSession, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return the campaign-wide ledger, oldest first.

        Tracking rows created before the ledger existed contribute their
        reconstructed history, so the feed is never empty for a campaign that
        already has engagement data.

        Args:
            campaign: The campaign.
            db: Active session.
            limit: Maximum number of events returned.

        Returns:
            Ledger entries enriched with the recipient's name and address.
        """
        # An outer join keeps campaign-level rows (a generic USB drop, an
        # anonymous QR scan) in the feed: those have no employee record, and an
        # inner join silently dropped their events from the audit trail.
        rows = (
            await db.execute(
                select(EmailTracking, HumanAsset)
                .outerjoin(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .where(EmailTracking.campaign_id == campaign.id)
            )
        ).all()
        if not rows:
            return []
        grouped = await self._events_for([tracking.id for tracking, _ in rows], db)

        feed: list[dict[str, Any]] = []
        for tracking, employee in rows:
            events = grouped.get(tracking.id) or synthesized_events(tracking)
            if employee is not None:
                employee_id = employee.id
                employee_name = employee.full_name
                employee_email = employee.email
                department = employee.department
            else:
                employee_id = tracking.id
                employee_name = (
                    "USB drop endpoint"
                    if (tracking.channel or "").strip().lower() == "usb"
                    else "Unknown visitor"
                )
                employee_email = tracking.submitted_email or "—"
                department = (
                    "Physical USB drop"
                    if (tracking.channel or "").strip().lower() == "usb"
                    else "Unattributed"
                )
            for event in events:
                feed.append(
                    {
                        **event,
                        "employee_id": employee_id,
                        "employee_name": employee_name,
                        "employee_email": employee_email,
                        "department": department,
                    }
                )
        feed.sort(key=lambda item: item["occurred_at"])
        return feed[:limit]


__all__ = [
    "EVENT_LABELS",
    "InteractionReportService",
    "build_record",
    "serialize_interaction",
    "synthesized_events",
]
