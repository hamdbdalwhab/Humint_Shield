"""Campaign launcher.

Drives the full lifecycle of a simulation:

* validates the campaign is still a ``draft``,
* materialises one :class:`~app.models.EmailTracking` row per target,
* personalises the template per recipient,
* dispatches the email through :class:`BrevoEmailService`, and
* aggregates per-employee results for the reporting endpoints.

Each recipient is committed independently so a single failure never rolls back
the whole campaign.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
)
from app.services.brevo_email_service import BrevoEmailService
from app.services.template_service import TemplatePersonalizer
from app.services.tracking_service import latest_submitted_values

logger = get_logger(__name__)


def _now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class CampaignLaunchError(RuntimeError):
    """Raised when a campaign cannot be launched."""


class CampaignLauncher:
    """Orchestrates campaign execution."""

    def __init__(
        self,
        email_service: BrevoEmailService | None = None,
        personalizer: TemplatePersonalizer | None = None,
    ) -> None:
        """Initialise the launcher.

        Args:
            email_service: Email transport (injectable for tests).
            personalizer: Template renderer (injectable for tests).
        """
        self.email_service = email_service or BrevoEmailService()
        self.personalizer = personalizer or TemplatePersonalizer()

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

        target_ids = [self._coerce_uuid(t) for t in (campaign.target_employee_ids or [])]
        target_ids = [t for t in target_ids if t is not None]
        if not target_ids:
            raise CampaignLaunchError("campaign has no target employees")

        template = await self._load_template(db, campaign)
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
                    db, campaign, template, organization, employee_id
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
    ) -> dict[str, Any]:
        """Send the campaign email to one employee.

        Args:
            db: Active session.
            campaign: The campaign being launched.
            template: The (active) template to render.
            organization: Owning organization (for ``{{company_name}}``).
            employee_id: Target employee.

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
                "message_id": existing.brevo_message_id,
            }

        tracking_uuid = uuid.uuid4()
        tracking = existing or EmailTracking(
            campaign_id=campaign.id,
            employee_id=employee.id,
            email_template_id=template.id,
            tracking_uuid=tracking_uuid,
        )
        tracking.email_template_id = template.id
        db.add(tracking)
        await db.flush()

        rendered = self.personalizer.personalize(
            template, employee, organization, tracking.tracking_uuid, self._base_url()
        )

        correlation_id = f"{campaign.id}:{employee.id}"
        response = await self.email_service.send_training_email(
            to_email=employee.email,
            to_name=employee.full_name,
            subject=rendered["subject"],
            html_content=rendered["html_content"],
            correlation_id=correlation_id,
        )

        if response.get("success"):
            tracking.sent_at = _now()
            tracking.brevo_message_id = response.get("message_id")
            tracking.delivered_at = _now()
            employee.total_tests_received = (employee.total_tests_received or 0) + 1
            employee.last_test_date = _now()
            await db.flush()
            return {
                "success": True,
                "email": employee.email,
                "error": None,
                "message_id": response.get("message_id"),
            }

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
                select(EmailTracking, HumanAsset)
                .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .where(EmailTracking.campaign_id == campaign.id)
                .order_by(EmailTracking.created_at.asc())
            )
        ).all()

        employees: list[dict[str, Any]] = []
        opened = clicked = completed = submitted = 0
        for tracking, employee in rows:
            status = "failed"
            if tracking.sent_at is not None:
                status = "sent"
            if tracking.opened_at is not None:
                status = "opened"
            if tracking.clicked_at is not None:
                status = "clicked"
            if tracking.form_submitted_at is not None:
                status = "submitted"
            if tracking.completed_training_at is not None:
                status = "completed"
            opened += 1 if tracking.opened_at else 0
            clicked += 1 if tracking.clicked_at else 0
            submitted += 1 if tracking.form_submitted_at else 0
            completed += 1 if tracking.completed_training_at else 0
            employees.append(
                {
                    "employee_id": employee.id,
                    "name": employee.full_name,
                    "email": employee.email,
                    "department": employee.department,
                    "job_title": employee.job_title,
                    "status": status,
                    "sent_at": tracking.sent_at,
                    "opened_at": tracking.opened_at,
                    "clicked_at": tracking.clicked_at,
                    "submitted_at": tracking.form_submitted_at,
                    "completed_at": tracking.completed_training_at,
                    "form_viewed_at": tracking.form_viewed_at,
                    "reported_at": tracking.reported_at,
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
