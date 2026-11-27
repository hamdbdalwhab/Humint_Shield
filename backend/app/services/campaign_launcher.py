"""Campaign launcher.

Drives the full lifecycle of a simulation across email, SMS and WhatsApp:

* validates the campaign is still a ``draft``,
* materialises one :class:`~app.models.EmailTracking` row per target,
* personalises the template (or the operator's custom SMS text) per recipient,
* dispatches through Brevo (email) or TextBee (SMS), and
* aggregates per-employee results for the reporting endpoints.

Each recipient is committed independently so a single failure never rolls back
the whole campaign.  For SMS the TextBee gateway acknowledgement is stored as
``submitted``; delivery is confirmed by the Android device, not by this server.
"""
from __future__ import annotations

import asyncio
import time
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
from app.services.employee_service import get_send_blockers
from app.services.template_personalizer import TemplatePersonalizer
from app.services.tracking_service import latest_submitted_values
from app.services.illyvoip_service import IllyVoIPService
from app.services.landing_page_resolver import LandingPageResolver
from app.services.short_link_service import ShortLinkService
from app.services.sms_segments import segment_info
from app.services.textbee_service import TextBeeService, is_e164_phone
from app.services.whatsapp_service import WhatsAppService

logger = get_logger(__name__)

PHONE_CHANNELS = frozenset({"sms", "whatsapp"})
#: Real outbound voice calls through IllyVoIP (not the manual vishing page).
VOICE_CHANNELS = frozenset({"voice"})


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
        illyvoip_service: IllyVoIPService | None = None,
        textbee_service: TextBeeService | None = None,
        whatsapp_service: WhatsAppService | None = None,
        short_link_service: ShortLinkService | None = None,
        landing_page_resolver: LandingPageResolver | None = None,
    ) -> None:
        """Initialise the launcher.

        Args:
            email_service: Email transport (injectable for tests).
            personalizer: Template renderer (injectable for tests).
            illyvoip_service: Real voice/TTS transport (injectable for tests).
            textbee_service: TextBee SMS gateway (injectable for tests).
            whatsapp_service: WA-AKG WhatsApp gateway (injectable for tests).
            short_link_service: SMS short-link factory (injectable for tests).
            landing_page_resolver: SMS landing-page router (injectable).
        """
        self.email_service = email_service or BrevoService()
        self.personalizer = personalizer or TemplatePersonalizer()
        self.landing_page_resolver = landing_page_resolver or LandingPageResolver()
        self.illyvoip_service = illyvoip_service or IllyVoIPService(
            settings=self.personalizer.settings
        )
        self.textbee_service = textbee_service or TextBeeService(
            settings=self.personalizer.settings
        )
        self.whatsapp_service = whatsapp_service or WhatsAppService(
            settings=self.personalizer.settings
        )
        #: Monotonic timestamp of the last WhatsApp send, for anti-ban pacing.
        self._last_whatsapp_send_at: float | None = None
        self.short_link_service = short_link_service or ShortLinkService(
            settings=self.personalizer.settings
        )

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
        # launcher itself must refuse a phone/voice campaign with missing
        # credentials.  Voice readiness comes from IllyVoIP.
        if channel in VOICE_CHANNELS:
            readiness = self.illyvoip_service.configuration_status()
            if not readiness.get("valid"):
                missing = ", ".join(readiness.get("missing") or [])
                raise CampaignLaunchError(
                    "VOICE delivery is not configured"
                    + (f"; set {missing}" if missing else "")
                )
        elif channel == "whatsapp":
            # WhatsApp is delivered by the self-hosted WA-AKG gateway.
            readiness = self.whatsapp_service.configuration_status()
            if not readiness.get("valid"):
                missing = ", ".join(readiness.get("missing") or [])
                raise CampaignLaunchError(
                    "WhatsApp delivery is not configured; set "
                    + (missing or "WA_AKG_API_KEY")
                    + " in backend/.env"
                )
        elif channel in PHONE_CHANNELS:
            # SMS is delivered exclusively by the TextBee Android gateway.
            readiness = self.textbee_service.configuration_status()
            if not readiness.get("valid"):
                missing = ", ".join(readiness.get("missing") or [])
                raise CampaignLaunchError(
                    "SMS delivery is not configured; set "
                    + (missing or "TEXTBEE_API_KEY")
                    + " in backend/.env"
                )

        target_ids = [self._coerce_uuid(t) for t in (campaign.target_employee_ids or [])]
        target_ids = [t for t in target_ids if t is not None]
        if not target_ids:
            if channel in ("qr", "usb"):
                campaign.status = "active"
                campaign.launched_at = _now()
                campaign.total_targets = 0
                campaign.sent_count = 1
                campaign.failed_count = 0

                # Ensure at least one generic tracking row exists for USB physical drop
                if channel == "usb":
                    from app.models import EmailTracking
                    import uuid
                    existing_tracking = (
                        await db.execute(
                            select(EmailTracking)
                            .where(EmailTracking.campaign_id == campaign.id, EmailTracking.channel == "usb")
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if existing_tracking is None:
                        generic_tracking = EmailTracking(
                            campaign_id=campaign.id,
                            employee_id=None,
                            channel="usb",
                            tracking_uuid=uuid.uuid4(),
                        )
                        db.add(generic_tracking)
                        await db.flush()

                await db.commit()
                return {
                    "campaign_id": cid,
                    "total": 1,
                    "sent": 1,
                    "failed": 0,
                    "failures": [],
                    "blocked": [],
                    "blocked_count": 0,
                }
            raise CampaignLaunchError("campaign has no target employees")

        template = await self._load_template(db, campaign)
        adaptive_templates = await self._load_adaptive_templates(db, campaign, template)
        organization = await db.get(Organization, campaign.organization_id)

        # Module 3/4 guardrails: pre-compute every employee who must be skipped.
        # Mandatory-training campaigns bypass both the cooldown and blacklist.
        blockers = (
            await get_send_blockers(
                db,
                organization,
                target_ids,
                exclude_campaign_id=cid,
                is_mandatory_training=bool(campaign.is_mandatory_training),
            )
            if organization is not None
            else {}
        )
        blocked: list[dict[str, Any]] = []

        campaign.status = "active"
        campaign.launched_at = _now()
        campaign.total_targets = len(target_ids)
        campaign.sent_count = 0
        campaign.failed_count = 0
        await db.commit()

        failures: list[dict[str, Any]] = []
        sent = 0

        for employee_id in target_ids:
            if employee_id in blockers:
                blocked.append(blockers[employee_id])
                logger.info(
                    "campaign_recipient_blocked",
                    campaign_id=str(cid),
                    employee_id=str(employee_id),
                    reason=blockers[employee_id].get("reason"),
                )
                continue
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

            if getattr(campaign, "auto_retest_failed", False):
                try:
                    from app.worker.tasks import retest_failed_campaign_employees
                    retest_failed_campaign_employees.apply_async(
                        args=[str(campaign.id)],
                        countdown=72 * 3600,
                    )
                    logger.info("retest_task_scheduled", campaign_id=str(campaign.id), delay_hours=72)
                except Exception as exc:
                    logger.warning("retest_task_schedule_failed", campaign_id=str(campaign.id), error=str(exc))

        result = {
            "campaign_id": cid,
            "total": len(target_ids),
            "sent": sent,
            "failed": len(failures),
            "failures": failures,
            "blocked": blocked,
            "blocked_count": len(blocked),
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
        if channel in PHONE_CHANNELS or channel in VOICE_CHANNELS:
            if not (employee.phone or "").strip():
                phone_error = (
                    f"employee has no phone number; {channel} campaigns require "
                    "an E.164 number (for example +966500000000)"
                )
            elif not is_e164_phone(employee.phone):
                phone_error = (
                    f"employee phone '{employee.phone}' is not in E.164 format; "
                    "update it to a value such as +966500000000"
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

        # A campaign that names a template sends that template verbatim.  Elo-band
        # rotation is opt-in so an operator's explicit choice is never replaced by
        # a different scenario, subject or language at launch time.
        if self._adaptive_templates_enabled(campaign):
            selected_template = self._select_adaptive_template(
                template, adaptive_templates or [template], employee, channel
            )
        else:
            selected_template = template

        tracking_uuid = uuid.uuid4()
        if channel == "email":
            provider_name = "brevo"
        elif channel in SIMULATION_CHANNELS:
            provider_name = "simulation"
        elif channel in VOICE_CHANNELS:
            provider_name = "illyvoip"
        elif channel == "whatsapp":
            # WhatsApp has exactly one transport: the WA-AKG gateway.
            provider_name = "wa-akg"
        elif channel == "sms":
            # SMS has exactly one transport: the TextBee Android gateway.
            provider_name = "textbee"
        else:
            provider_name = "simulation"
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
        if not tracking.short_code:
            from app.services.tracking_service import TrackingService
            tracking.short_code = TrackingService.generate_short_code()
        db.add(tracking)
        await db.flush()
        if channel in VOICE_CHANNELS:
            # The real call can take tens of seconds.  Persist the tracking row
            # before the provider request so a worker crash, status poll or
            # hangup can always correlate the call to the campaign recipient.
            await db.commit()

        if phone_error is not None:
            tracking.delivery_status = "failed"
            tracking.delivery_error = phone_error[:500]
            await db.flush()
            if channel in VOICE_CHANNELS:
                await db.commit()
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
                short_code=tracking.short_code,
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
        elif channel in VOICE_CHANNELS:
            raw_config = campaign.channel_config or {}
            voice_config: dict[str, Any] = {}
            if isinstance(raw_config, dict):
                candidate = raw_config.get("voice") or raw_config.get("vishing")
                if isinstance(candidate, dict):
                    voice_config = candidate
            # Ring-only verification: dial and hang up at the first ring, with
            # no script and therefore no TTS credit spent.
            ring_only = bool(voice_config.get("ring_only"))
            script = ""
            if not ring_only:
                script = str(voice_config.get("script") or "").strip()
                if script:
                    # An explicit script may contain merge tags; resolve them per
                    # recipient so the TTS never reads "{{first_name}}" aloud.
                    script = self.personalizer.render_voice_script(
                        script,
                        selected_template,
                        employee,
                        organization,
                        tracking.tracking_uuid,
                        self._base_url(),
                    )
                if not script:
                    script = self.personalizer.personalize_voice(
                        selected_template,
                        employee,
                        organization,
                        tracking.tracking_uuid,
                        self._base_url(),
                    )
            answer_timeout = voice_config.get("answer_timeout_seconds")
            if answer_timeout is not None:
                try:
                    answer_timeout = float(answer_timeout)
                except (TypeError, ValueError):
                    answer_timeout = None
            try:
                if ring_only:
                    call_result = await self.illyvoip_service.ring_only_call(
                        employee.phone or "",
                        campaign_id=campaign.id,
                        tracking_uuid=tracking.tracking_uuid,
                        record=False,
                    )
                else:
                    call_result = await self.illyvoip_service.place_vishing_call(
                        employee.phone or "",
                        script,
                        campaign_id=campaign.id,
                        tracking_uuid=tracking.tracking_uuid,
                        language=voice_config.get("language"),
                        voice=voice_config.get("voice"),
                        answer_timeout_seconds=answer_timeout,
                        record=voice_config.get("record"),
                    )
                response = {
                    "success": True,
                    "message_id": call_result.get("call_control_id"),
                    "error": None,
                    "call_result": call_result,
                }
            except Exception as exc:  # noqa: BLE001 - transport failures are data
                logger.error(
                    "campaign_voice_provider_exception",
                    campaign_id=str(campaign.id),
                    employee_id=str(employee.id),
                    channel=channel,
                    error=str(exc),
                    error_code=getattr(exc, "error_code", None),
                    provider_status_code=getattr(exc, "status_code", None),
                )
                call_id = None
                fields = getattr(exc, "fields", None)
                if isinstance(fields, dict):
                    call_id = fields.get("call_control_id")
                rang = bool(fields.get("rang")) if isinstance(fields, dict) else False
                ring_seconds = (
                    fields.get("ring_seconds") if isinstance(fields, dict) else None
                )
                response = {
                    "success": False,
                    "message_id": call_id,
                    "error": str(exc),
                    "call_control_id": call_id,
                    "rang": rang,
                    "ring_seconds": ring_seconds,
                }
        else:
            is_whatsapp = channel == "whatsapp"
            sms_config = self._channel_config(
                campaign, "whatsapp" if is_whatsapp else "sms"
            )
            custom_message = str(sms_config.get("custom_message") or "").strip()
            if custom_message:
                # The operator's own wording replaces the template body; merge
                # tags and {{link}} are still resolved per recipient.
                text_content = self.personalizer.render_custom_message(
                    custom_message,
                    selected_template,
                    employee,
                    organization,
                    tracking.tracking_uuid,
                    self._base_url(),
                    short_code=tracking.short_code,
                )
            else:
                text_content = self.personalizer.personalize_text(
                    selected_template,
                    employee,
                    organization,
                    tracking.tracking_uuid,
                    self._base_url(),
                )["text_content"]
            try:
                if is_whatsapp:
                    message_id = await self._send_whatsapp(
                        employee.phone or "",
                        text_content,
                        tracking,
                        db,
                        department=employee.department,
                        manual_landing_page=sms_config.get("selected_landing_page"),
                    )
                else:
                    message_id = await self._send_sms(
                        employee.phone or "",
                        text_content,
                        tracking,
                        db,
                        department=employee.department,
                        manual_landing_page=sms_config.get("selected_landing_page"),
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
            elif channel in VOICE_CHANNELS:
                tracking.delivered_at = _now()
                if ring_only:
                    # Nothing was spoken, so the call is not a completed
                    # simulation; record exactly what happened.
                    tracking.delivery_status = "ring_only"
                else:
                    tracking.completed_at = _now()
                    tracking.delivery_status = "completed"
            else:
                tracking.delivery_status = "submitted"
            tracking.delivery_error = None
            employee.total_tests_received = (employee.total_tests_received or 0) + 1
            employee.last_test_date = _now()
            await db.flush()

            if channel == "sms":
                await self._record_sms_sent(db, tracking)
            elif channel == "whatsapp":
                await self._record_whatsapp_sent(db, tracking)

            if channel in VOICE_CHANNELS:
                await self._record_voice_events(
                    db,
                    tracking,
                    response.get("call_result") or {},
                    ring_only=ring_only,
                )

            return {
                "success": True,
                "email": employee.email,
                "error": None,
                "message_id": response.get("message_id"),
            }

        tracking.delivery_status = "failed"
        tracking.delivery_error = (response.get("error") or "send failed")[:500]
        if channel in VOICE_CHANNELS:
            tracking.failed_at = _now()
            if response.get("message_id"):
                tracking.provider_message_id = str(response["message_id"])[:255]
            if response.get("rang"):
                # The handset actually rang and nobody answered: that is an
                # outcome of the simulation, not a delivery error by the system.
                rang_for = response.get("ring_seconds")
                rang_text = (
                    f" after {float(rang_for):.0f}s of ringing"
                    if isinstance(rang_for, (int, float)) and rang_for
                    else ""
                )
                tracking.delivery_status = "no_answer"
                tracking.delivery_error = (
                    "No answer: the recipient's phone rang"
                    f"{rang_text} and the carrier ended the call before pickup."
                )[:500]
            await self._record_voice_failure(
                db,
                tracking,
                tracking.delivery_error,
                not_answered=bool(response.get("rang")),
            )
        await db.flush()
        return {
            "success": False,
            "email": employee.email,
            "error": response.get("error") or "send failed",
            "message_id": None,
        }

    async def _record_sms_sent(
        self, db: AsyncSession, tracking: EmailTracking
    ) -> None:
        """Append ``sms_sent`` evidence for an accepted SMS.

        A ledger failure must never turn an accepted provider message into a
        campaign failure.
        """
        try:
            from app.services.tracking_service import TrackingService

            await TrackingService().log_sms_sent(
                tracking.tracking_uuid,
                db,
                provider=self.personalizer.settings.sms_provider_effective,
                batch_id=tracking.provider_message_id,
                characters=int(getattr(tracking, "sms_characters", 0) or 0),
            )
        except Exception:  # noqa: BLE001 - the message is already accepted
            logger.exception(
                "campaign_sms_audit_failed",
                tracking_uuid=str(tracking.tracking_uuid),
            )

    async def _record_whatsapp_sent(
        self, db: AsyncSession, tracking: EmailTracking
    ) -> None:
        """Append ``whatsapp_sent`` evidence for an accepted WhatsApp message.

        A ledger failure must never turn an accepted message into a campaign
        failure.
        """
        try:
            from app.services.tracking_service import TrackingService

            await TrackingService().log_whatsapp_sent(
                tracking.tracking_uuid,
                db,
                provider=self.personalizer.settings.whatsapp_provider_effective,
                message_id=tracking.provider_message_id,
                characters=0,
            )
        except Exception:  # noqa: BLE001 - the message is already accepted
            logger.exception(
                "campaign_whatsapp_audit_failed",
                tracking_uuid=str(tracking.tracking_uuid),
            )

    async def _record_voice_events(
        self,
        db: AsyncSession,
        tracking: EmailTracking,
        call_result: dict[str, Any],
        *,
        ring_only: bool = False,
    ) -> None:
        """Append the real-call lifecycle to the interaction ledger.

        A ledger failure must never turn a completed provider call into a
        campaign failure; the tracking row has already been updated.
        """
        try:
            from app.services.tracking_service import (
                EVENT_VISHING_CALL_ANSWERED,
                EVENT_VISHING_CALL_COMPLETED,
                EVENT_VISHING_CALL_PLACED,
                EVENT_VISHING_TTS_PLAYED,
                TrackingService,
            )

            call_id = str(call_result.get("call_control_id") or "") or None
            details = {
                "provider": "illyvoip",
                "call_control_id": call_id,
                "state": call_result.get("state"),
                "call_status": call_result.get("call_status"),
                "duration_seconds": call_result.get("duration_seconds"),
                "tts_media": call_result.get("tts_media"),
                "answered_at": call_result.get("answered_at"),
                "ended_at": call_result.get("ended_at"),
                "failure_reason": call_result.get("failure_reason"),
                # An answered timestamp is not proof a person listened: the
                # destination may never have rung, or a voicemail/announcement
                # may have answered.  Persist the evidence that distinguishes them.
                "rang": bool(call_result.get("rang")),
                "answer_delay_seconds": call_result.get("answer_delay_seconds"),
                "answer_suspect_auto": bool(call_result.get("answer_suspect_auto")),
            }
            service = TrackingService()
            async with db.begin_nested():
                await service.log_vishing_event(
                    tracking.tracking_uuid,
                    EVENT_VISHING_CALL_PLACED,
                    db,
                    details=details,
                    provider_message_id=call_id,
                    delivery_status="ring_only" if ring_only else "calling",
                )
                if ring_only:
                    # Verification call: it rang and was cut before any audio.
                    # There is no answer and no completion to record.
                    return
                answered_by_human_evidence = bool(
                    call_result.get("answered_at")
                    and call_result.get("rang")
                    and not call_result.get("answer_suspect_auto")
                )
                if answered_by_human_evidence:
                    await service.log_vishing_event(
                        tracking.tracking_uuid,
                        EVENT_VISHING_CALL_ANSWERED,
                        db,
                        details=details,
                        provider_message_id=call_id,
                        delivery_status="answered",
                    )
                if call_result.get("tts_media"):
                    await service.log_vishing_event(
                        tracking.tracking_uuid,
                        EVENT_VISHING_TTS_PLAYED,
                        db,
                        details={
                            "call_control_id": call_id,
                            "tts_media": call_result.get("tts_media"),
                            "tts_charge": call_result.get("tts_charge"),
                        },
                        provider_message_id=call_id,
                        delivery_status="answered",
                    )
                await service.log_vishing_event(
                    tracking.tracking_uuid,
                    EVENT_VISHING_CALL_COMPLETED,
                    db,
                    details=details,
                    provider_message_id=call_id,
                    delivery_status="completed",
                )
        except Exception:  # noqa: BLE001 - the call already completed
            logger.exception(
                "campaign_voice_audit_failed",
                campaign_id=str(tracking.campaign_id),
                employee_id=str(tracking.employee_id),
            )

    async def _record_voice_failure(
        self,
        db: AsyncSession,
        tracking: EmailTracking,
        error: str | None,
        *,
        not_answered: bool = False,
    ) -> None:
        """Append a failed real-call attempt to the interaction ledger."""
        try:
            from app.services.tracking_service import (
                EVENT_VISHING_CALL_FAILED,
                EVENT_VISHING_CALL_NOT_ANSWERED,
                TrackingService,
            )

            event_type = (
                EVENT_VISHING_CALL_NOT_ANSWERED
                if not_answered
                else EVENT_VISHING_CALL_FAILED
            )
            async with db.begin_nested():
                await TrackingService().log_vishing_event(
                    tracking.tracking_uuid,
                    event_type,
                    db,
                    details={
                        "provider": "illyvoip",
                        "error": error,
                        "call_control_id": tracking.provider_message_id,
                    },
                    provider_message_id=tracking.provider_message_id,
                    delivery_status=tracking.delivery_status,
                    delivery_error=error,
                )
        except Exception:  # noqa: BLE001 - the call failure is already recorded
            logger.exception(
                "campaign_voice_failure_audit_failed",
                campaign_id=str(tracking.campaign_id),
                employee_id=str(tracking.employee_id),
            )

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
                .outerjoin(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
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
            emp_id = employee.id if employee is not None else tracking.id
            emp_name = (
                employee.full_name
                if employee is not None
                else (tracking.submitted_username or tracking.submitted_email or "Unknown QR Visitor")
            )
            emp_email = employee.email if employee is not None else (tracking.submitted_email or "—")
            emp_dept = employee.department if employee is not None else "QR Capture"
            emp_job = employee.job_title if employee is not None else "External / Mobile"
            immunity = float(employee.immunity_score) if (employee is not None and employee.immunity_score is not None) else None
            behavioral_cat = employee.behavioral_category if employee is not None else "unaware"
            elo_val = int(employee.elo_score or 1000) if employee is not None else 1000
            threat_val = threat_level_for_elo(employee.elo_score) if employee is not None else "medium"

            employees.append(
                {
                    "employee_id": emp_id,
                    "tracking_uuid": tracking.tracking_uuid,
                    "name": emp_name,
                    "email": emp_email,
                    "phone": employee.phone if employee is not None else None,
                    "channel": tracking.channel or campaign.channel or "email",
                    "department": emp_dept,
                    "job_title": emp_job,
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
                    "client_context": tracking.client_context or {},
                    "is_reported_safe": tracking.is_reported_safe,
                    "open_count": tracking.open_count or 0,
                    "click_count": tracking.click_count or 0,
                    "submission_count": tracking.submission_count or 0,
                    "submitted_identifier": tracking.submitted_identifier,
                    "submitted_fields": tracking.submitted_fields or None,
                    "submitted_values": latest_submitted_values(tracking),
                    "password_length": tracking.password_length,
                    "immunity_score": immunity,
                    "behavioral_category": behavioral_cat,
                    "elo_score": elo_val,
                    "threat_level": threat_val,
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

        is_qr = (campaign.channel or "").strip().lower() == "qr"
        total = campaign.total_targets or len(employees)
        if is_qr and total == 0:
            total = len(employees)
        sent = campaign.sent_count or (len(employees) if is_qr else 0)
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
        # A department-specific lure must never be swapped for another
        # department's scenario: the landing-page skin is derived from it.
        department = (fallback.target_department or "").strip().lower()
        if department and department != "all":
            templates = [
                template
                for template in templates
                if (template.target_department or "").strip().lower() == department
            ]
        if fallback.id not in {template.id for template in templates}:
            templates.append(fallback)
        return templates

    @staticmethod
    def _adaptive_templates_enabled(campaign: EmailCampaign) -> bool:
        """Return ``True`` when the campaign opted into adaptive rotation.

        ``channel_config.adaptive_templates`` is the explicit switch.  When it
        is absent the campaign's own template is delivered exactly as authored.
        """
        raw = campaign.channel_config or {}
        if not isinstance(raw, dict):
            return False
        value = raw.get("adaptive_templates")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value) if isinstance(value, (int, float)) else False

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
        if channel in SIMULATION_CHANNELS or channel in VOICE_CHANNELS:
            # Simulation channels and real voice calls reuse an active email
            # template as their scenario/reference content; delivery happens
            # outside the email provider.
            return template
        if (template.channel or "email") != channel:
            raise CampaignLaunchError(
                f"template channel '{template.channel}' does not match campaign channel '{channel}'"
            )
        return template

    @staticmethod
    def _sms_config(campaign: EmailCampaign) -> dict[str, Any]:
        """Return the campaign's ``channel_config.sms`` block as a dict."""
        raw = campaign.channel_config or {}
        if not isinstance(raw, dict):
            return {}
        candidate = raw.get("sms")
        return dict(candidate) if isinstance(candidate, dict) else {}

    @staticmethod
    def _channel_config(campaign: EmailCampaign, key: str) -> dict[str, Any]:
        """Return one ``channel_config[key]`` block as a dict."""
        raw = campaign.channel_config or {}
        if not isinstance(raw, dict):
            return {}
        candidate = raw.get(key)
        if not isinstance(candidate, dict):
            return {}
        return dict(candidate)

    async def _send_sms(
        self,
        phone: str,
        text: str,
        tracking: EmailTracking,
        db: AsyncSession,
        *,
        department: str | None = None,
        manual_landing_page: str | None = None,
    ) -> str:
        """Deliver one simulated SMS through TextBee and return its batch id.

        The call to action is a short link (``{SHORT_LINK_BASE_URL}/s/{code}``)
        that records the click and then opens the SMS landing page; the long
        tracking URL never appears in the message.  The destination carries the
        resolved landing page as ``?page=…`` so the recipient always sees the
        scenario that matches the message and their department.

        Args:
            phone: Recipient in E.164 format.
            text: Message body (template render or custom text).
            tracking: The recipient's tracking row.
            db: Active session.
            department: Recipient department (highest-priority override).
            manual_landing_page: The administrator's explicit page choice.

        Raises:
            RuntimeError: When TextBee is not configured or rejects the
                message; the launcher records it as a per-recipient failure.
        """
        settings = self.personalizer.settings
        base = self._base_url().rstrip("/")
        landing_page = self.landing_page_resolver.resolve(
            message=text,
            department=department,
            manual=manual_landing_page,
        )
        link = await self.short_link_service.ensure_link(
            db, tracking, landing_page=landing_page
        )
        tracking.short_code = link.code
        short_url = await self.short_link_service.display_url(db, link)
        click_url = f"{base}/api/v1/track/click/{tracking.tracking_uuid}"
        sms_url = f"{base}/api/v1/track/sms/{tracking.tracking_uuid}"
        body = (text or "").replace(click_url, short_url).replace(sms_url, short_url)
        body = body.strip()
        if short_url not in body:
            body = f"{body} {short_url}".strip()

        # Arabic copy is UCS-2: 70 characters per segment, not 160.  The exact
        # count is kept on the tracking row so the interaction ledger records
        # what was actually sent and billed.
        segments = segment_info(body)
        tracking.sms_characters = segments.units
        tracking.sms_segments = segments.segments

        logger.info(
            "campaign_sms_landing_page_resolved",
            tracking_uuid=str(tracking.tracking_uuid),
            department=department,
            landing_page=landing_page,
            characters=segments.units,
            encoding=segments.encoding,
            segments=segments.segments,
        )
        if segments.concatenated:
            logger.warning(
                "campaign_sms_multipart",
                tracking_uuid=str(tracking.tracking_uuid),
                encoding=segments.encoding,
                segments=segments.segments,
                characters_per_segment=segments.characters_per_segment,
            )

        if not settings.textbee_configured:
            raise RuntimeError(
                "TextBee is not configured: set TEXTBEE_API_KEY (and "
                "TEXTBEE_DEVICE_ID) in backend/.env"
            )
        result = await self.textbee_service.send_sms(phone, body)
        if not result.get("success"):
            detail = str(result.get("error") or "the gateway rejected the message")
            status_code = result.get("status_code")
            raise RuntimeError(
                "TextBee delivery failed: "
                + detail
                + (
                    " (check that the TextBee device is online and the API key "
                    "is valid)"
                    if status_code is None or status_code == 401
                    else ""
                )
            )
        return str(result.get("batch_id") or "")

    async def _send_whatsapp(
        self,
        phone: str,
        text: str,
        tracking: EmailTracking,
        db: AsyncSession,
        *,
        department: str | None = None,
        manual_landing_page: str | None = None,
    ) -> str:
        """Deliver one WhatsApp message through WA-AKG and return its message id.

        The body keeps the short link (``{SHORT_LINK_BASE_URL}/s/{code}``) so the
        long tracking URL never appears in the chat, and the landing page is
        resolved with the same department/keyword rules as SMS.  Between two
        outbound messages the launcher waits the configured 10-30 second
        anti-ban pause.

        Raises:
            RuntimeError: When WA-AKG is not configured, the session is
                disconnected or the provider rejects the message.
        """
        settings = self.personalizer.settings
        base = self._base_url().rstrip("/")
        landing_page = self.landing_page_resolver.resolve(
            message=text,
            department=department,
            manual=manual_landing_page,
        )
        link = await self.short_link_service.ensure_link(
            db, tracking, landing_page=landing_page
        )
        tracking.short_code = link.code
        short_url = await self.short_link_service.display_url(db, link)
        whatsapp_url = f"{base}/api/v1/track/whatsapp/{tracking.tracking_uuid}"
        click_url = f"{base}/api/v1/track/click/{tracking.tracking_uuid}"
        body = (text or "").replace(whatsapp_url, short_url).replace(click_url, short_url)
        body = body.replace("{{link}}", short_url).strip()
        if short_url not in body:
            body = f"{body} {short_url}".strip()

        logger.info(
            "campaign_whatsapp_landing_page_resolved",
            tracking_uuid=str(tracking.tracking_uuid),
            department=department,
            landing_page=landing_page,
            characters=len(body),
        )

        readiness = self.whatsapp_service.configuration_status()
        if not readiness.get("valid"):
            missing = ", ".join(readiness.get("missing") or [])
            raise RuntimeError(
                "WhatsApp (WA-AKG) is not configured: set "
                + (missing or "WA_AKG_API_KEY")
                + " in backend/.env"
            )

        # Anti-ban pacing: never fire two messages closer than the configured
        # minimum, measured from the end of the previous send.
        if self._last_whatsapp_send_at is not None:
            delay = self.whatsapp_service.delay_between_messages()
            elapsed = time.monotonic() - self._last_whatsapp_send_at
            remaining = delay - elapsed
            if remaining > 0:
                logger.info(
                    "campaign_whatsapp_pause",
                    seconds=round(remaining, 1),
                    tracking_uuid=str(tracking.tracking_uuid),
                )
                await asyncio.sleep(remaining)

        result = await self.whatsapp_service.send_whatsapp_message(
            phone, body, tracking.tracking_uuid
        )
        self._last_whatsapp_send_at = time.monotonic()
        if not result.get("success"):
            error_code = result.get("error_code")
            detail = str(result.get("error") or "the gateway rejected the message")
            hint = {
                "session_disconnected": " (scan the QR code again in the WA-AKG dashboard)",
                "invalid_number": " (the number is not registered on WhatsApp)",
                "rate_limited": " (WhatsApp is throttling this session; slow the campaign down)",
                "timeout": " (the WA-AKG instance did not answer)",
            }.get(str(error_code), "")
            raise RuntimeError(f"WhatsApp delivery failed: {detail}{hint}")
        return str(result.get("message_id") or "")

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
