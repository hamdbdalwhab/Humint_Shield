"""Tracking endpoints (unauthenticated).

The per-recipient ``tracking_uuid`` is an unguessable secret and is the only
credential these endpoints require.  Responses are deliberately minimal and
cache-busting so that email clients and proxies never cache a tracking hit.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    User,
)
from app.schemas import (
    ReportSafeResponse,
    TrackingCompleteResponse,
    TrainingCompleteRequest,
    TrainingInteractionResponse,
    TrainingSubmission,
)
from app.services.attack_chain import build_compromised_assets
from app.services.template_service import TRANSPARENT_GIF
from app.services.tracking_service import TrackingService

logger = get_logger(__name__)
router = APIRouter(
    prefix="/track",
    tags=["tracking"],
    dependencies=[Depends(rate_limit(limit=600, scope="tracking"))],
)

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _client_ip(request: Request) -> str | None:
    """Return the client IP, honouring the reverse proxy header."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get(
    "/context/{tracking_uuid}",
    summary="Public context for the React landing experience",
)
async def track_context(
    tracking_uuid: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return the minimum recipient context needed by the landing page.

    The tracking UUID is the bearer secret; it is already present in the
    recipient's own email link. Only the recipient's own name, address and
    campaign metadata are returned, never any captured values.
    """
    if not _valid_uuid(tracking_uuid):
        return {"found": False}
    uid = uuid.UUID(tracking_uuid)
    row = (
        await db.execute(
            select(EmailTracking, HumanAsset, Organization, EmailCampaign, EmailTemplate)
            .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
            .join(Organization, Organization.id == HumanAsset.organization_id)
            .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
            .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
            .where(EmailTracking.tracking_uuid == uid)
        )
    ).first()
    if row is None:
        return {"found": False}
    tracking, employee, organization, campaign, template = row
    template_name = template.name if template is not None else ""
    lowered = template_name.lower()
    skin = "hr" if ("hr" in lowered or "employee records" in lowered) else "microsoft"
    if "microsoft" in lowered or "password" in lowered:
        sender_name = "Microsoft 365"
    elif "hr" in lowered or "records" in lowered:
        sender_name = "Human Resources"
    elif "ceo" in lowered or "brief" in lowered:
        sender_name = "Office of the CEO"
    elif "invoice" in lowered:
        sender_name = "Northstar Supply · Billing"
    elif "drive" in lowered or "document" in lowered:
        sender_name = "Google Drive"
    else:
        sender_name = "IT Service Desk"
    return {
        "found": True,
        "first_name": employee.first_name or "",
        "last_name": employee.last_name or "",
        "email": employee.email,
        "company_name": organization.name,
        "template_name": template_name,
        "subject": (template.subject if template is not None else "Security notification"),
        "sender_name": sender_name,
        "campaign_name": campaign.name,
        "channel": tracking.channel or "email",
        "skin": skin,
        "form_submitted": tracking.submitted_at is not None,
        "already_completed": tracking.completed_at is not None,
        "quiz_score": tracking.quiz_score,
        "quiz_total": tracking.quiz_total,
        "is_reported_safe": bool(tracking.is_reported_safe),
        "compromised_assets": build_compromised_assets(tracking, template, campaign),
    }


@router.post(
    "/form-view/{tracking_uuid}",
    response_model=TrainingInteractionResponse,
    summary="Record that the React credential form was rendered",
)
async def track_form_view(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrainingInteractionResponse:
    """Append a form-view event without changing the recipient's funnel stage."""
    if not _valid_uuid(tracking_uuid):
        return TrainingInteractionResponse(success=False, message="Invalid tracking identifier")
    try:
        row = await TrackingService().mark_form_viewed(
            tracking_uuid, db, _client_ip(request), request.headers.get("user-agent")
        )
        if row is None:
            await db.rollback()
            return TrainingInteractionResponse(success=False, message="Tracking record not found")
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - never break the landing page
        await db.rollback()
        logger.error("track_form_view_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrainingInteractionResponse(success=False, message="Unable to record the view")
    return TrainingInteractionResponse(
        success=True,
        first_time=False,
        message="Form view recorded.",
    )


@router.get(
    "/open/{tracking_uuid}",
    summary="Open-tracking pixel (returns a 1x1 transparent GIF)",
    response_class=Response,
)
async def track_open(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Log an email open and return the transparent tracking GIF.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        request: Incoming request (for IP/User-Agent).
        db: Active session.

    Returns:
        The 47-byte transparent GIF with no-cache headers.  Unknown UUIDs also
        receive the GIF so that probes cannot distinguish valid recipients.
    """
    service = TrackingService()
    if _valid_uuid(tracking_uuid):
        try:
            await service.log_open(
                tracking_uuid, _client_ip(request), request.headers.get("user-agent"), db
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - never break the pixel
            await db.rollback()
            logger.error("track_open_failed", tracking_uuid=tracking_uuid, error=str(exc))
    return Response(content=TRANSPARENT_GIF, media_type="image/gif", headers=NO_CACHE_HEADERS)


@router.get(
    "/click/{tracking_uuid}",
    summary="Click tracker (302 to the simulation landing page)",
)
async def track_click(
    tracking_uuid: str,
    request: Request,
    url: str | None = Query(None, max_length=2048, description="Original link target"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Log a click then redirect the recipient to the correct experience.

    Email recipients must see the simulated sign-in form that matches the
    campaign before the awareness reveal. SMS and WhatsApp links keep their
    existing direct-to-training behaviour because those channels do not carry
    credential forms.

    The original ``url`` is recorded in the logs for red-flag analysis; the
    recipient is never sent to the original target because the message is an
    authorized training simulation.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        request: Incoming request.
        url: The original (unused) link target.
        db: Active session.

    Returns:
        A 302 redirect to ``{base_url}/phish/{tracking_uuid}`` for email, or
        ``{base_url}/training/{tracking_uuid}`` for SMS/WhatsApp.
    """
    settings = get_settings()
    channel = "email"
    if _valid_uuid(tracking_uuid):
        try:
            row = await TrackingService().log_click(
                tracking_uuid, _client_ip(request), request.headers.get("user-agent"), db
            )
            # Capture the channel before commit expires the ORM instance.
            if row is not None:
                channel = (getattr(row, "channel", None) or "email").strip().lower()
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - redirect regardless
            await db.rollback()
            logger.error("track_click_failed", tracking_uuid=tracking_uuid, error=str(exc))
    base_url = settings.base_url.rstrip("/")
    target = (
        f"{base_url}/phish/{tracking_uuid}"
        if channel == "email"
        else f"{base_url}/training/{tracking_uuid}"
    )
    logger.info(
        "click_redirect",
        tracking_uuid=tracking_uuid,
        channel=channel,
        original_url=url,
        target=target,
    )
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS)


@router.post(
    "/complete/{tracking_uuid}",
    response_model=TrackingCompleteResponse,
    summary="Mark the micro-training as complete",
)
async def track_complete(
    tracking_uuid: str,
    payload: TrainingCompleteRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> TrackingCompleteResponse:
    """Record training completion and the interactive quiz result.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        payload: ``{"score": 4, "total": 5}`` from the training page. The body
            is optional for backwards compatibility; when omitted the quiz
            result is not overwritten.
        db: Active session.

    Returns:
        The completion status, quiz result and refreshed immunity score.
    """
    if not _valid_uuid(tracking_uuid):
        return TrackingCompleteResponse(
            success=False, message="Invalid tracking identifier"
        )
    prior_completion = await db.scalar(
        select(EmailTracking.completed_at).where(
            EmailTracking.tracking_uuid == uuid.UUID(tracking_uuid)
        )
    )
    try:
        row = await TrackingService().log_completion(
            tracking_uuid,
            db,
            score=payload.score if payload else None,
            total=payload.total if payload else None,
        )
        if row is None:
            await db.rollback()
            return TrackingCompleteResponse(
                success=False, message="Tracking record not found"
            )
        employee = await db.get(HumanAsset, row.employee_id)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("track_complete_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrackingCompleteResponse(success=False, message="Unable to record completion")
    score_text = (
        f" Quiz: {row.quiz_score}/{row.quiz_total}."
        if row.quiz_score is not None and row.quiz_total
        else ""
    )
    already_completed = prior_completion is not None
    return TrackingCompleteResponse(
        success=True,
        already_completed=already_completed,
        message=(
            f"Training already completed — no duplicate completion counted.{score_text}"
            if already_completed
            else f"Training completed. Thank you — +5 awareness points.{score_text}"
        ),
        quiz_score=row.quiz_score,
        quiz_total=row.quiz_total,
        immunity_score=float(employee.immunity_score) if employee and employee.immunity_score is not None else None,
        behavioral_category=employee.behavioral_category if employee else None,
    )


@router.post(
    "/submit/{tracking_uuid}",
    response_model=TrainingInteractionResponse,
    summary="Record a simulated credential-form submission",
)
async def track_submit(
    tracking_uuid: str,
    payload: TrainingSubmission,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrainingInteractionResponse:
    """Record what the recipient typed into the training-page form.

    Every value the form contained is captured: the identifier, the password
    and any additional named fields.  The verbatim mapping is encrypted with
    AES-256-GCM before storage; the API response and the logs never echo it.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        payload: Everything the recipient typed plus non-secret client context.
        request: Incoming request (for IP/User-Agent).
        db: Active session.

    Returns:
        ``{"success", "first_time", "message"}``.  Unknown UUIDs return
        ``success=False`` with a 200 status so the page can stay generic.
    """
    if not _valid_uuid(tracking_uuid):
        return TrainingInteractionResponse(
            success=False, message="Invalid tracking identifier"
        )
    try:
        row = await TrackingService().log_submission(
            tracking_uuid,
            payload.identifier,
            payload.password,
            payload.password_length,
            payload.fields,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
            client=payload.client,
        )
        if row is None:
            await db.rollback()
            return TrainingInteractionResponse(
                success=False, message="Tracking record not found"
            )
        first_time = (row.submission_count or 0) == 1
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - never break the landing page
        await db.rollback()
        logger.error("track_submit_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrainingInteractionResponse(
            success=False, message="Unable to record submission"
        )
    return TrainingInteractionResponse(
        success=True,
        first_time=first_time,
        message=(
            "Your response was recorded."
            if first_time
            else "Your response was updated."
        ),
    )


@router.post(
    "/report/{tracking_uuid}",
    response_model=TrainingInteractionResponse,
    summary="Flag the simulation as suspicious from the training page",
)
async def track_report(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrainingInteractionResponse:
    """Record that the recipient recognised the message as phishing.

    Reporting is the desired behaviour: it creates a row in the report inbox,
    increments the employee's report counter and refreshes their score.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        request: Incoming request (for IP/User-Agent).
        db: Active session.

    Returns:
        ``{"success", "first_time", "message"}``.
    """
    if not _valid_uuid(tracking_uuid):
        return TrainingInteractionResponse(
            success=False, message="Invalid tracking identifier"
        )
    try:
        report = await TrackingService().log_simulation_report(
            tracking_uuid,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - never break the landing page
        await db.rollback()
        logger.error("track_report_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrainingInteractionResponse(
            success=False, message="Unable to record the report"
        )
    if report is None:
        return TrainingInteractionResponse(
            success=False, message="Already reported — thank you."
        )
    return TrainingInteractionResponse(
        success=True,
        first_time=True,
        message="Thank you — reporting suspicious mail is exactly the right behaviour.",
    )


@router.post(
    "/report-safe/{tracking_uuid}",
    response_model=ReportSafeResponse,
    summary="Record an administrator-confirmed 'report safe' outcome",
)
async def track_report_safe(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> ReportSafeResponse:
    """Mark a recipient as safe after an out-of-band phishing report.

    This is intentionally authenticated: the public training page can report a
    simulation, but only an administrator can assert that an employee reported
    the message through another channel. The action is idempotent, stores a real
    audit event, fixes the quiz result at 5/5 and sets the employee's immunity
    score to 100%.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        request: Admin request (for IP/User-Agent evidence).
        db: Active session.
        user: Authenticated admin or manager.

    Returns:
        The resulting safe-report state.
    """
    if not _valid_uuid(tracking_uuid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tracking identifier",
        )

    row = await db.scalar(
        select(EmailTracking).where(
            EmailTracking.tracking_uuid == uuid.UUID(tracking_uuid)
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking record not found",
        )
    employee = await db.get(HumanAsset, row.employee_id)
    if employee is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    if user.organization_id is not None and user.organization_id != employee.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tracking record belongs to another organization",
        )

    try:
        result = await TrackingService().mark_reported_safe(
            tracking_uuid,
            db,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            actor=user.username,
        )
        if result is None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking record not found",
            )
        _, updated_employee, already = result
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error(
            "track_report_safe_failed",
            tracking_uuid=tracking_uuid,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to record the safe report",
        ) from exc

    return ReportSafeResponse(
        success=True,
        message=(
            "Already recorded as reported safe."
            if already
            else "Reported safe: quiz 5/5 and immunity set to 100%."
        ),
        quiz_score=5,
        quiz_total=5,
        immunity_score=float(updated_employee.immunity_score)
        if updated_employee.immunity_score is not None
        else None,
        behavioral_category=updated_employee.behavioral_category,
        already_reported_safe=already,
    )


def _valid_uuid(value: str) -> bool:
    """Return ``True`` when ``value`` parses as a UUID."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False
