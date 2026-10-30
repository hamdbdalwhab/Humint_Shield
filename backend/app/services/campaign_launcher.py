"""Campaign launcher.

Drives the full lifecycle of a simulation across email, SMS and WhatsApp:

* validates the campaign is still a ``draft``,
* materialises one :class:`~app.models.EmailTracking` row per target,
* personalises the template per recipient and per channel,
* dispatches through Brevo (email) or Vonage (SMS / WhatsApp), and
* aggregates per-employee results for the reporting endpoints.

Each recipient is committed independently so a single failure never rolls back
the whole campaign.  For SMS/WhatsApp the provider acknowledgement is stored as
``submitted``; ``delivered`` and ``read`` are only set by the real Vonage
webhooks.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.logging_config import get_logger
from app.models import (
    CHANNELS,
    SIMULATION_CHANNELS,
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
)
from app.services.brevo_service import BrevoService
from app.services.elo_engine import (
    difficulty_band,
    difficulty_range,
    threat_level_for_elo,
)
from app.services.template_personalizer import TemplatePersonalizer
from app.services.quickconnect_service import QuickConnectService
from app.services.vonage_service import VonageService, is_e164_phone

logger = get_logger(__name__)

PHONE_CHANNELS = frozenset({"sms", "whatsapp"})


def _now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class CampaignLaunchError(RuntimeError):
    """Raised when a campaign cannot be launched."""


class CampaignLauncher:
    """Orchestrates campaign execution."""

    def __init__(
        self,
        email_service: BrevoService | None = None,
        personalizer: TemplatePersonalizer | None = None,
        vonage_service: VonageService | None = None,
        quickconnect_service: QuickConnectService | None = None,
    ) -> None:
        """Initialise the launcher.

        Args:
            email_service: Email transport (injectable for tests).
            personalizer: Template renderer (injectable for tests).
            vonage_service: SMS/WhatsApp transport (injectable for tests).
            quickconnect_service: QuickConnect SMS/WhatsApp transport (injectable for tests).
        """
        self.email_service = email_service or BrevoService()
        self.personalizer = personalizer or TemplatePersonalizer()
        self._injected_vonage = vonage_service is not None
        self._injected_quickconnect = quickconnect_service is not None
        self.vonage_service = vonage_service or VonageService(settings=self.personalizer.settings)
        self.quickconnect_service = quickconnect_service or QuickConnectService(
            settings=self.personalizer.settings
        )

    def _is_quickconnect_active(self, channel: str) -> bool:
        """Determine whether QuickConnect or Vonage is the active transport."""
        if self._injected_quickconnect:
            return True
        if self._injected_vonage:
            return False
        provider = (
            self.personalizer.settings.sms_provider
            if channel == "sms"
            else self.personalizer.settings.whatsapp_provider
        )
        if (provider or "").strip().lower() == "vonage":
            return False
        return self.personalizer.settings.quickconnect_configured

    # ------------------------------------------------------------------ #
    # Launch
    # ------------------------------------------------------------------ #
    async def launch_campaign(
        self, campaign_id: uuid.UUID | str, db: AsyncSession
    ) -> dict[str, Any]:
        """Send a campaign to every target.

        Args:
            campaign_id: Campaign to launch.
            db: Active session.

        Returns:
            ``{"campaign_id", "total", "sent", "failed", "failures": [...]}``.

        Raises:
            CampaignLaunchError: When the campaign does not exist, is not a
                draft, has no targets, or its template is inactive/missing.
        """
        cid = self._coerce_uuid(campaign_id)
        if cid is None:
            raise CampaignLaunchError("invalid campaign id")

        campaign = await db.get(EmailCampaign, cid)
        if campaign is None:
            raise CampaignLaunchError("campaign not found")
        if campaign.status != "draft":
            raise CampaignLaunchError(
                f"campaign is '{campaign.status}'; only 'draft' campaigns can be launched"
            )
        channel = (campaign.channel or "email").strip().lower()
        if channel not in CHANNELS:
            raise CampaignLaunchError(f"unsupported campaign channel: {channel!r}")
        campaign.channel = channel

        # Background workers and direct callers bypass the API preflight, so the
        # launcher itself must refuse a phone campaign with missing credentials.
        if channel in PHONE_CHANNELS:
            use_quickconnect = self._is_quickconnect_active(channel)
            phone_svc = self.quickconnect_service if use_quickconnect else self.vonage_service

            configuration_status = getattr(phone_svc, "configuration_status", None)
            if callable(configuration_status):
                readiness = configuration_status(channel)
                if not readiness.get("valid"):
                    missing = ", ".join(readiness.get("missing") or [])
                    raise CampaignLaunchError(
                        f"{channel.upper()} delivery is not configured"
                        + (f"; set {missing}" if missing else "")
                    )

        target_ids = [self._coerce_uuid(t) for t in (campaign.target_employee_ids or [])]
        target_ids = [t for t in target_ids if t is not None]
        if not target_ids:
            raise CampaignLaunchError("campaign has no target employees")

        template = await self._load_template(db, campaign)
        adaptive_templates = await self._load_adaptive_templates(db, campaign, template)
        organization = await db.get(Organization, campaign.organization_id)

        campaign.status = "active"
        campaign.launched_at = _now()
        campaign.total_targets = len(target_ids)
        campaign.sent_count = 0
        campaign.failed_count = 0
        await db.commit()

        failures: list[dict[str, Any]] = []
        sent = 0

        for employee_id in target_ids:
            try:
                outcome = await self._send_to_employee(
                    db,
                    campaign,
                    template,
                    organization,
                    employee_id,
                    adaptive_templates=adaptive_templates,
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-recipient failures
                logger.error(
                    "campaign_send_exception",
                    campaign_id=str(cid),
                    employee_id=str(employee_id),
                    error=str(exc),
                )
                await db.rollback()
                campaign = await db.get(EmailCampaign, cid)
                if campaign is None:  # pragma: no cover - defensive
                    break
                # ``rollback`` expires every loaded instance. Re-load the
                # template and organization before the next recipient so an
                # isolated transport exception cannot turn into a lazy-load
                # error for the rest of the campaign.
                template = (
                    await db.get(EmailTemplate, campaign.template_id)
                    if campaign.template_id
                    else None
                )
                organization = await db.get(Organization, campaign.organization_id)
                if template is None or organization is None:  # pragma: no cover
                    break
                adaptive_templates = await self._load_adaptive_templates(
                    db, campaign, template
                )
                campaign.failed_count = (campaign.failed_count or 0) + 1
                await db.commit()
                failures.append(
                    {
                        "employee_id": employee_id,
                        "email": "unknown",
                        "error": str(exc),
                    }
                )
                continue

            if outcome["success"]:
                sent += 1
                campaign = await db.get(EmailCampaign, cid)
                if campaign is not None:
                    campaign.sent_count = (campaign.sent_count or 0) + 1
                await db.commit()
            else:
                campaign = await db.get(EmailCampaign, cid)
                if campaign is not None:
                    campaign.failed_count = (campaign.failed_count or 0) + 1
                await db.commit()
                failures.append(
                    {
                        "employee_id": employee_id,
                        "email": outcome["email"],
                        "error": outcome["error"] or "unknown error",
                    }
                )

        campaign = await db.get(EmailCampaign, cid)
        if campaign is not None:
            campaign.status = "completed"
            campaign.completed_at = _now()
            await db.commit()

        result = {
            "campaign_id": cid,
            "total": len(target_ids),
            "sent": sent,
            "failed": len(failures),
            "failures": failures,
        }
        logger.info(
            "campaign_launched",
            campaign_id=str(cid),
            total=result["total"],
            sent=sent,
            failed=result["failed"],
        )
        return result

    async def _send_to_employee(
        self,
        db: AsyncSession,
        campaign: EmailCampaign,
        template: EmailTemplate,
        organization: Organization | None,
        employee_id: uuid.UUID,
        adaptive_templates: list[EmailTemplate] | None = None,
    ) -> dict[str, Any]:
        """Send one campaign message to one employee through the channel provider.

        Args:
            db: Active session.
            campaign: The campaign being launched.
            template: The campaign's fallback template.
            organization: Owning organization (for ``{{company_name}}``).
            employee_id: Target employee.
            adaptive_templates: Active templates in the campaign's channel.  The
                launcher picks the next one in the employee's Elo band; when the
                list is empty or the band has no candidates it uses ``template``.

        Returns:
            ``{"success": bool, "email": str, "error": str | None, "message_id": str | None}``.
        """
        employee = await db.get(HumanAsset, employee_id)
        if employee is None or employee.organization_id != campaign.organization_id:
            return {
                "success": False,
                "email": "unknown",
                "error": "employee not found in organization",
                "message_id": None,
            }
        if not employee.is_active:
            return {
                "success": False,
                "email": employee.email,
                "error": "employee is inactive",
                "message_id": None,
            }

        channel = (campaign.channel or "email").strip().lower()
        phone_error: str | None = None
        if channel in PHONE_CHANNELS:
            if not (employee.phone or "").strip():
                phone_error = (
                    f"employee has no phone number; {channel} campaigns require "
                    "an E.164 number (for example +966500000000)"
                )
            elif not is_e164_phone(employee.phone):
                clean_digits = re.sub(r"\D", "", (employee.phone or ""))
                if not (len(clean_digits) in (9, 10)):
                    phone_error = (
                        f"employee phone '{employee.phone}' is not in a recognized format; "
                        "update it to a value such as +967771234567 or 771234567"
                    )

        # Idempotency: never send twice for the same (campaign, employee).
        existing = await db.scalar(
            select(EmailTracking).where(
                EmailTracking.campaign_id == campaign.id,
                EmailTracking.employee_id == employee.id,
            )
        )
        if existing is not None and existing.sent_at is not None:
            return {
                "success": True,
                "email": employee.email,
                "error": None,
                "message_id": existing.provider_message_id,
            }

        selected_template = self._select_adaptive_template(
            template, adaptive_templates or [template], employee, channel
        )

        tracking_uuid = uuid.uuid4()
        channel_provider = (
            self.personalizer.settings.sms_provider
            if channel == "sms"
            else self.personalizer.settings.whatsapp_provider
        )
        use_quickconnect = self._is_quickconnect_active(channel)
        provider_name = (
            "brevo"
            if channel == "email"
            else "simulation"
            if channel in SIMULATION_CHANNELS
            else ("quickconnect" if use_quickconnect else "vonage")
        )
        tracking = existing or EmailTracking(

            campaign_id=campaign.id,
            employee_id=employee.id,
            template_id=selected_template.id,
            channel=channel,
            provider=provider_name,
            tracking_uuid=tracking_uuid,
        )
        tracking.template_id = selected_template.id
        tracking.channel = channel
        tracking.provider = provider_name
        # A failed previous attempt may have left no provider id; a reused row
        # must never retain an id belonging to the failed send.
        if tracking.sent_at is None:
            tracking.provider_message_id = None
        db.add(tracking)
        await db.flush()

        if phone_error is not None:
            tracking.delivery_status = "failed"
            tracking.delivery_error = phone_error[:500]
            await db.flush()
            logger.warning(
                "campaign_send_phone_invalid",
                campaign_id=str(campaign.id),
                employee_id=str(employee.id),
                channel=channel,
            )
            return {
                "success": False,
                "email": employee.email,
                "error": phone_error,
                "message_id": None,
            }

        correlation_id = f"{campaign.id}:{employee.id}"
        response: dict[str, Any]

        if channel in SIMULATION_CHANNELS:
            # These channels are delivered outside a provider: the operator
            # prints the QR poster or shares the unique simulation link.  The
            # tracking row is still materialised so every interaction is
            # measurable through the same funnel and Elo pipeline.
            response = {"success": True, "message_id": None, "error": None}
        elif channel == "email":
            rendered = self.personalizer.personalize(
                selected_template,
                employee,
                organization,
                tracking.tracking_uuid,
                self._base_url(),
            )
            try:
                sender = getattr(self.email_service, "send_email", None)
                if sender is not None:
                    # The channel contract is exactly three arguments;
                    # provider-level correlation ids and display names are optional.
                    response = await sender(
                        to_email=employee.email,
                        subject=rendered["subject"],
                        html_content=rendered["html_content"],
                    )
                else:
                    # Backwards compatibility for injected doubles created
                    # before the channel-neutral send_email contract.
                    response = await self.email_service.send_training_email(
                        to_email=employee.email,
                        to_name=employee.full_name,
                        subject=rendered["subject"],
                        html_content=rendered["html_content"],
                        correlation_id=correlation_id,
                    )
            except Exception as exc:  # noqa: BLE001 - transport failures are data
                logger.error(
                    "campaign_send_provider_exception",
                    campaign_id=str(campaign.id),
                    employee_id=str(employee.id),
                    channel=channel,
                    error=str(exc),
                )
                response = {"success": False, "message_id": None, "error": str(exc)}
        else:
            rendered_text = self.personalizer.personalize_text(
                selected_template,
                employee,
                organization,
                tracking.tracking_uuid,
                self._base_url(),
            )
            use_quickconnect = self._is_quickconnect_active(channel)

            try:
                if channel == "sms":
                    if use_quickconnect:
                        message_id = await self.quickconnect_service.send_sms(
                            employee.phone or "", rendered_text["text_content"]
                        )
                    else:
                        message_id = await self.vonage_service.send_sms(
                            employee.phone or "", rendered_text["text_content"]
                        )
                else:
                    if use_quickconnect:
                        message_id = await self.quickconnect_service.send_whatsapp(
                            employee.phone or "", rendered_text["text_content"]
                        )
                    else:
                        message_id = await self.vonage_service.send_whatsapp(
                            employee.phone or "", rendered_text["text_content"]
                        )
                response = {"success": True, "message_id": message_id, "error": None}
            except Exception as exc:  # noqa: BLE001 - transport failures are data
                logger.error(
                    "campaign_send_provider_exception",
                    campaign_id=str(campaign.id),
                    employee_id=str(employee.id),
                    channel=channel,
                    error=str(exc),
                )
                response = {"success": False, "message_id": None, "error": str(exc)}

        if response.get("success"):
            tracking.sent_at = _now()
            tracking.provider_message_id = response.get("message_id")
            if channel == "email":
                # Preserve the email channel's historical semantics: acceptance
                # by the transport is its delivery marker. SMS/WhatsApp get their
                # delivered timestamp from the provider webhook only.
                tracking.delivered_at = _now()
                tracking.delivery_status = "delivered"
            elif channel in SIMULATION_CHANNELS:
                tracking.delivered_at = _now()
                tracking.delivery_status = "available"
            else:
                tracking.delivery_status = "submitted"
            tracking.delivery_error = None
            employee.total_tests_received = (employee.total_tests_received or 0) + 1
            employee.last_test_date = _now()
            await db.flush()
            return {
                "success": True,
                "email": employee.email,
                "error": None,
                "message_id": response.get("message_id"),
            }

        tracking.delivery_status = "failed"
        tracking.delivery_error = (response.get("error") or "send failed")[:500]
        await db.flush()
        return {
            "success": False,
            "email": employee.email,
            "error": response.get("error") or "send failed",
            "message_id": None,
        }

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #
    async def get_campaign_results(
        self, campaign_id: uuid.UUID | str, db: AsyncSession
    ) -> dict[str, Any]:
        """Build the full results view for a campaign.

        Args:
            campaign_id: Campaign to report on.
            db: Active session.

        Returns:
            ``{"campaign", "stats", "employees"}``.

        Raises:
            CampaignLaunchError: When the campaign does not exist.
        """
        cid = self._coerce_uuid(campaign_id)
        campaign = await db.get(EmailCampaign, cid) if cid else None
        if campaign is None:
            raise CampaignLaunchError("campaign not found")

        rows = (
            await db.execute(
                select(EmailTracking, HumanAsset, EmailTemplate)
                .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
                .where(EmailTracking.campaign_id == campaign.id)
                .order_by(EmailTracking.created_at.asc())
            )
        ).all()

        employees: list[dict[str, Any]] = []
        opened = clicked = completed = submitted = 0
        for tracking, employee, delivered_template in rows:
            status = "failed"
            if tracking.sent_at is not None:
                status = "sent"
            if tracking.opened_at is not None:
                status = "opened"
            if tracking.clicked_at is not None:
                status = "clicked"
            if tracking.submitted_at is not None:
                status = "submitted"
            if tracking.completed_at is not None:
                status = "completed"
            if tracking.reported_at is not None and tracking.submitted_at is None:
                status = "reported_safe"
            if tracking.is_reported_safe:
                status = "reported_safe"
            opened += 1 if tracking.opened_at else 0
            clicked += 1 if tracking.clicked_at else 0
            submitted += 1 if tracking.submitted_at else 0
            completed += 1 if tracking.completed_at else 0
            employees.append(
                {
                    "employee_id": employee.id,
                    "tracking_uuid": tracking.tracking_uuid,
                    "name": employee.full_name,
                    "email": employee.email,
                    "phone": employee.phone,
                    "channel": tracking.channel or campaign.channel or "email",
                    "department": employee.department,
                    "job_title": employee.job_title,
                    "status": status,
                    "sent_at": tracking.sent_at,
                    "delivered_at": tracking.delivered_at,
                    "delivery_status": tracking.delivery_status,
                    "delivery_error": tracking.delivery_error,
                    "read_at": tracking.read_at,
                    "failed_at": tracking.failed_at,
                    "provider_message_id": tracking.provider_message_id,
                    "opened_at": tracking.opened_at,
                    "clicked_at": tracking.clicked_at,
                    "submitted_at": tracking.submitted_at,
                    "completed_at": tracking.completed_at,
                    "form_viewed_at": tracking.viewed_at,
                    "reported_at": tracking.reported_at,
                    "quiz_score": tracking.quiz_score,
                    "quiz_total": tracking.quiz_total,
                    "is_reported_safe": tracking.is_reported_safe,
                    "open_count": tracking.open_count or 0,
                    "click_count": tracking.click_count or 0,
                    "submission_count": tracking.submission_count or 0,
                    "submitted_identifier": tracking.submitted_identifier,
                    "submitted_fields": tracking.submitted_fields or None,
                    "submitted_values": latest_submitted_values(tracking),
                    "password_length": tracking.password_length,
                    "immunity_score": float(employee.immunity_score)
                    if employee.immunity_score is not None
                    else None,
                    "behavioral_category": employee.behavioral_category,
                    "elo_score": int(employee.elo_score or 1000),
                    "threat_level": threat_level_for_elo(employee.elo_score),
                    "template_name": (
                        delivered_template.name if delivered_template is not None else None
                    ),
                    "template_difficulty": (
                        delivered_template.difficulty_level
                        if delivered_template is not None
                        else None
                    ),
                    "error": None,
                }
            )

        sent = campaign.sent_count or 0
        total = campaign.total_targets or len(employees)
        stats = {
            "total": total,
            "sent": sent,
            "failed": campaign.failed_count or 0,
            "opened": opened,
            "clicked": clicked,
            "submitted": submitted,
            "completed": completed,
            "open_rate": round((opened / sent * 100) if sent else 0.0, 2),
            "click_rate": round((clicked / sent * 100) if sent else 0.0, 2),
            "submission_rate": round((submitted / sent * 100) if sent else 0.0, 2),
            "completion_rate": round((completed / sent * 100) if sent else 0.0, 2),
        }
        return {"campaign": campaign, "stats": stats, "employees": employees}

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    async def _load_adaptive_templates(
        self,
        db: AsyncSession,
        campaign: EmailCampaign,
        fallback: EmailTemplate,
    ) -> list[EmailTemplate]:
        """Load every active template available to the campaign's channel.

        The campaign's own template is included as a fallback even if a data
        migration left it outside the active filter.  The launcher never sends a
        template from another organization or channel.
        """
        channel = (campaign.channel or "email").strip().lower()
        rows = (
            (
                await db.execute(
                    select(EmailTemplate)
                    .where(
                        EmailTemplate.organization_id == campaign.organization_id,
                        EmailTemplate.channel == channel,
                        EmailTemplate.is_active.is_(True),
                    )
                    .order_by(
                        EmailTemplate.difficulty_level.asc(),
                        EmailTemplate.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        templates = list(rows)
        if fallback.id not in {template.id for template in templates}:
            templates.append(fallback)
        return templates

    def _select_adaptive_template(
        self,
        fallback: EmailTemplate,
        candidates: list[EmailTemplate],
        employee: HumanAsset,
        channel: str,
    ) -> EmailTemplate:
        """Pick the next template for one employee from the correct Elo band.

        The pool is rotated by ``employee.total_tests_received`` so the same
        recipient does not receive the same template forever.  If the band is
        empty (for example an organization only has medium templates), the
        campaign template is used and the fallback is logged rather than
        silently selecting an out-of-band template.
        """
        elo = int(employee.elo_score or 1000)
        band = difficulty_band(elo)
        low, high = difficulty_range(elo)
        pool = [
            template
            for template in candidates
            if (template.channel or "email") == channel
            and template.is_active
            and low <= int(template.difficulty_level or 0) <= high
        ]
        if not pool:
            logger.info(
                "adaptive_template_fallback",
                organization_id=str(employee.organization_id),
                employee_id=str(employee.id),
                elo_score=elo,
                band=band,
                template_id=str(fallback.id),
                difficulty=fallback.difficulty_level,
            )
            return fallback

        # Prefer the middle of the band, then rotate through equally suitable
        # templates.  The rotation is per employee and advances after each send
        # because the launcher increments ``total_tests_received``.
        target = (low + high) / 2
        ordered = sorted(
            pool,
            key=lambda template: (
                abs(int(template.difficulty_level or 0) - target),
                int(template.difficulty_level or 0),
                template.name.lower(),
            ),
        )
        index = int(employee.total_tests_received or 0) % len(ordered)
        selected = ordered[index]
        logger.info(
            "adaptive_template_selected",
            employee_id=str(employee.id),
            elo_score=elo,
            band=band,
            template_id=str(selected.id),
            difficulty=selected.difficulty_level,
            pool_size=len(ordered),
        )
        return selected

    async def _load_template(self, db: AsyncSession, campaign: EmailCampaign) -> EmailTemplate:
        """Load and validate the campaign's template.

        Raises:
            CampaignLaunchError: When the template is missing or inactive.
        """
        if campaign.template_id is None:
            raise CampaignLaunchError("campaign has no template assigned")
        template = await db.get(EmailTemplate, campaign.template_id)
        if template is None:
            raise CampaignLaunchError("campaign template not found")
        if not template.is_active:
            raise CampaignLaunchError("campaign template is inactive")
        channel = (campaign.channel or "email").strip().lower()
        if channel in SIMULATION_CHANNELS:
            # Simulation channels reuse an active email template as their
            # scenario/reference content; delivery happens outside a provider.
            return template
        if (template.channel or "email") != channel:
            raise CampaignLaunchError(
                f"template channel '{template.channel}' does not match campaign channel '{channel}'"
            )
        return template

    def _base_url(self) -> str:
        """Return the base URL used for tracking links."""
        return self.personalizer.settings.base_url

    @staticmethod
    def _coerce_uuid(value: Any) -> uuid.UUID | None:
        """Parse ``value`` into a UUID, returning ``None`` when invalid."""
        if isinstance(value, uuid.UUID):
            return value
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return None


async def launch_email_campaign(
    campaign_id: uuid.UUID | str,
    db: AsyncSession | None = None,
    *,
    launcher: CampaignLauncher | None = None,
) -> dict[str, Any]:
    """Launch a draft email campaign by id.

    This is the channel-facing entry point used by background workers and
    scripts.  When no session is supplied a short-lived session is opened and
    closed here; the launcher itself commits each recipient independently.

    Args:
        campaign_id: Campaign to launch.
        db: Optional active session (the API passes its request session).
        launcher: Optional injected launcher (used by tests).

    Returns:
        ``{"campaign_id", "total", "sent", "failed", "failures"}``.

    Raises:
        CampaignLaunchError: When the campaign is missing, not a draft, has no
            targets, or uses a channel whose provider is not configured.
    """
    instance = launcher or CampaignLauncher()
    if db is not None:
        return await instance.launch_campaign(campaign_id, db)

    factory = get_session_factory()
    async with factory() as session:
        return await instance.launch_campaign(campaign_id, session)


__all__ = ["CampaignLaunchError", "CampaignLauncher", "launch_email_campaign"]
