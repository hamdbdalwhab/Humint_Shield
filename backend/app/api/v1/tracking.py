"""Tracking endpoints (unauthenticated).

The per-recipient ``tracking_uuid`` is an unguessable secret and is the only
credential these endpoints require.  Responses are deliberately minimal and
cache-busting so that email clients and proxies never cache a tracking hit.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
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
    OTPVerifyRequest,
    QRProbeRequest,
    QRProbeResponse,
    QRSubmissionRequest,
    QRSubmissionResponse,
    ReportSafeResponse,
    SimulationChoiceRequest,
    SimulationChoiceResponse,
    TrackingCompleteResponse,
    TrainingCompleteRequest,
    TrainingInteractionResponse,
    TrainingSubmission,
)
from app.services.attack_chain import build_compromised_assets
from app.services.device_detector import detect_device_model
from app.services.email_design import branding_from_organization
from app.services.elo_engine import threat_level_for_elo
from app.services.geoip_service import lookup_ip_geolocation
from app.services.evidence_service import build_evidence
from app.services.landing_page_resolver import LandingPageResolver
from app.services.quishing_service import normalize_lure_type, resolve_poster_copy
from app.services.template_service import TRANSPARENT_GIF
from app.services.tracking_service import TrackingService, sanitize_telemetry

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
    """Return the client IP, honouring Cloudflare and reverse proxy headers."""
    for header in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        val = request.headers.get(header)
        if val and val.strip():
            return val.strip()
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
            .outerjoin(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
            .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
            .join(Organization, Organization.id == EmailCampaign.organization_id)
            .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.template_id)
            .where(EmailTracking.tracking_uuid == uid)
        )
    ).first()
    if row is None:
        campaign = await db.get(EmailCampaign, uid)
        if campaign is not None and (campaign.channel or "").strip().lower() == "qr":
            org = await db.get(Organization, campaign.organization_id)
            if org is not None:
                config = campaign.channel_config or {}
                branding = branding_from_organization(org, get_settings().base_url)
                poster = resolve_poster_copy(
                    config,
                    company_name=org.name,
                    department="",
                    primary_color=branding.primary_color,
                    logo=org.brand_logo_data,
                )
                qr_branding = {
                    "lure_type": poster.lure_type,
                    "company_name": poster.company_name,
                    "department": poster.department,
                    "month_label": poster.month_label,
                    "label": poster.label,
                    "headline": poster.headline,
                    "body": poster.body,
                    "cta": poster.cta,
                    "primary_color": poster.primary_color,
                    "accent_color": poster.accent_color,
                    "logo_url": (
                        config.get("qr", {}).get("logo_data_url")
                        if isinstance(config.get("qr"), dict)
                        else None
                    ) or branding.logo_url,
                }
                return {
                    "found": True,
                    "first_name": "",
                    "last_name": "",
                    "email": "",
                    "company_name": org.name,
                    "template_name": poster.headline,
                    "subject": poster.headline,
                    "sender_name": poster.company_name,
                    "campaign_name": campaign.name,
                    "campaign_id": str(campaign.id),
                    "channel": "qr",
                    "channel_config": config,
                    "skin": "hr",
                    "credential_provider": "hr",
                    "brand_primary_color": branding.primary_color,
                    "brand_logo_url": branding.logo_url,
                    "qr_branding": qr_branding,
                    "form_submitted": True,
                    "already_completed": False,
                    "quiz_score": None,
                    "quiz_total": 5,
                    "is_reported_safe": False,
                    "reported": False,
                    "otp_submitted": False,
                    "compromised_assets": [],
                }
        return {"found": False}
    tracking, employee, organization, campaign, template = row
    template_name = template.name if template is not None else ""
    lowered = template_name.lower()
    channel = (tracking.channel or "email").strip().lower()
    config = campaign.channel_config or {}
    requested_provider = str(config.get("credential_provider") or "").strip().lower()
    if requested_provider in {"microsoft", "google", "hr"}:
        skin = requested_provider
    elif "google" in lowered or "workspace" in lowered or "drive" in lowered:
        skin = "google"
    elif "hr" in lowered or "employee records" in lowered:
        skin = "hr"
    else:
        skin = "microsoft"

    if skin == "microsoft":
        sender_name = "Microsoft 365"
    elif skin == "google":
        sender_name = "Google Workspace"
    elif skin == "hr":
        sender_name = "Human Resources"
    elif "ceo" in lowered or "brief" in lowered:
        sender_name = "Office of the CEO"
    elif "invoice" in lowered:
        sender_name = "Northstar Supply · Billing"
    else:
        sender_name = "IT Service Desk"

    branding = branding_from_organization(organization, get_settings().base_url)
    qr_branding: dict[str, object] | None = None
    if channel == "qr":
        poster = resolve_poster_copy(
            config,
            company_name=organization.name,
            department="",
            primary_color=branding.primary_color,
            logo=organization.brand_logo_data,
        )
        qr_branding = {
            "lure_type": poster.lure_type,
            "company_name": poster.company_name,
            "department": poster.department,
            "month_label": poster.month_label,
            "label": poster.label,
            "headline": poster.headline,
            "body": poster.body,
            "cta": poster.cta,
            "primary_color": poster.primary_color,
            "accent_color": poster.accent_color,
            "logo_url": (
                config.get("qr", {}).get("logo_data_url")
                if isinstance(config.get("qr"), dict)
                else None
            )
            or branding.logo_url,
        }
    return {
        "found": True,
        "first_name": employee.first_name or "" if employee else "",
        "last_name": employee.last_name or "" if employee else "",
        "email": employee.email if employee else (tracking.submitted_email or ""),
        "company_name": organization.name,
        "template_name": template_name,
        # Department-aware SMS skin: the template's audience drives the page.
        "template_category": (
            (template.target_department or "").strip()
            if template is not None
            else ""
        )
        or None,
        "subject": (template.subject if template is not None else "Security notification"),
        "sender_name": sender_name,
        "campaign_name": campaign.name,
        "campaign_id": str(campaign.id),
        "channel": channel,
        "channel_config": config,
        # Resolved mobile-message landing page (department > manual choice >
        # keywords); the React page also accepts an explicit ``?page=`` override.
        "landing_page": (
            LandingPageResolver().resolve_for_config(
                (
                    config.get("whatsapp")
                    if isinstance(config.get("whatsapp"), dict)
                    else config.get("sms")
                )
                if isinstance(config, dict)
                else None,
                message=(
                    ((config.get("whatsapp") or config.get("sms")) or {}).get(
                        "custom_message"
                    )
                    if isinstance(config, dict)
                    else None
                ),
                department=getattr(employee, "department", None) if employee else None,
            )
            if channel in {"sms", "whatsapp"}
            else None
        ),
        "skin": skin,
        "credential_provider": skin,
        "brand_primary_color": branding.primary_color,
        "brand_logo_url": branding.logo_url,
        "qr_branding": qr_branding,
        "form_submitted": tracking.submitted_at is not None,
        "already_completed": tracking.completed_at is not None,
        "quiz_score": tracking.quiz_score,
        "quiz_total": tracking.quiz_total,
        "is_reported_safe": bool(tracking.is_reported_safe),
        "reported": tracking.reported_at is not None,
        "otp_submitted": bool(tracking.otp_submitted),
        "compromised_assets": build_compromised_assets(tracking, template, campaign),
    }


@router.get(
    "/evidence/{tracking_uuid}",
    summary="Forensic evidence report for the recipient's own interaction",
)
async def track_evidence(
    tracking_uuid: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return what the simulation captured, measured and cost.

    The tracking UUID is the bearer secret of the recipient's own link, so this
    exposes only that recipient's masked data: never a password, never another
    employee's values.  It powers the training page's evidence panel.
    """
    return await build_evidence(db, tracking_uuid)


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
            uid = uuid.UUID(tracking_uuid)
            channel = (
                await db.scalar(
                    select(EmailTracking.channel).where(
                        EmailTracking.tracking_uuid == uid
                    )
                )
                or "email"
            )
            channel = str(channel).strip().lower()
            service = TrackingService()
            if channel in {"qr", "vishing", "pretexting"}:
                # The advanced channels apply their own outcome-specific Elo
                # rules. A visit must not trigger the email -32 click penalty.
                await service.log_channel_visit(
                    tracking_uuid,
                    _client_ip(request),
                    request.headers.get("user-agent"),
                    db,
                    channel=channel,
                )
            else:
                await service.log_click(
                    tracking_uuid,
                    _client_ip(request),
                    request.headers.get("user-agent"),
                    db,
                )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - redirect regardless
            await db.rollback()
            logger.error("track_click_failed", tracking_uuid=tracking_uuid, error=str(exc))
    # Always redirect to the configured public origin.  A Host / X-Forwarded-Host
    # header is attacker-controlled and would otherwise turn these tracking
    # links into an open redirect to any domain.
    base_url = settings.base_url.rstrip("/")
    if channel == "email":
        target = f"{base_url}/phish/{tracking_uuid}"
    elif channel == "qr":
        target = f"{base_url}/simulation/qr/{tracking_uuid}"
    elif channel == "vishing":
        target = f"{base_url}/simulation/vishing/{tracking_uuid}"
    elif channel == "pretexting":
        target = f"{base_url}/simulation/ceo/{tracking_uuid}"
    else:
        target = f"{base_url}/training/{tracking_uuid}"
    logger.info(
        "click_redirect",
        tracking_uuid=tracking_uuid,
        channel=channel,
        original_url=url,
        target=target,
    )
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS)


@router.get(
    "/sms/{tracking_uuid}",
    summary="SMS link tracker (302 to the SMS landing page)",
)
async def track_sms_click(
    tracking_uuid: str,
    request: Request,
    page: str | None = Query(
        default=None,
        max_length=40,
        description="Landing-page slug resolved by the campaign launcher",
    ),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Record an SMS link click and send the recipient to the lure page.

    Following the link is score-neutral; the smishing penalty is applied once
    the landing-page form is submitted.

    Args:
        tracking_uuid: Per-recipient tracking UUID from the SMS body.
        request: Incoming request (for IP/User-Agent).
        page: Optional landing-page slug forwarded to the React page.
        db: Active session.

    Returns:
        A 302 redirect to ``{base_url}/sms-lure/{tracking_uuid}``, preserving
        ``?page=`` when the launcher supplied a landing page.
    """
    settings = get_settings()
    if _valid_uuid(tracking_uuid):
        try:
            await TrackingService().log_sms_click(
                tracking_uuid,
                _client_ip(request),
                request.headers.get("user-agent"),
                db,
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - redirect regardless
            await db.rollback()
            logger.error(
                "track_sms_click_failed", tracking_uuid=tracking_uuid, error=str(exc)
            )
    # Always redirect to the configured public origin.  A Host / X-Forwarded-Host
    # header is attacker-controlled and would otherwise turn these tracking
    # links into an open redirect to any domain.
    base_url = settings.base_url.rstrip("/")
    target = f"{base_url}/sms-lure/{tracking_uuid}"
    if page:
        target = f"{target}?page={quote(page, safe='')}"
    logger.info("sms_click_redirect", tracking_uuid=tracking_uuid, target=target)
    return RedirectResponse(
        url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS
    )


@router.get(
    "/whatsapp/{tracking_uuid}",
    summary="WhatsApp link tracker (302 to the WhatsApp lure page)",
)
async def track_whatsapp_click(
    tracking_uuid: str,
    request: Request,
    page: str | None = Query(
        default=None,
        max_length=40,
        description="Landing-page slug override; resolved server-side when empty",
    ),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Record a WhatsApp link click and redirect to the lure page.

    The landing page uses exactly the same resolution order as SMS: employee
    department, then the operator's manual choice, then keyword detection.
    Following the link is score-neutral.

    Returns:
        A 302 to ``{base_url}/whatsapp-lure/{uuid}?page=…``.
    """
    settings = get_settings()
    resolved_page = page
    if _valid_uuid(tracking_uuid):
        try:
            row = await TrackingService().log_whatsapp_click(
                tracking_uuid,
                _client_ip(request),
                request.headers.get("user-agent"),
                db,
            )
            if row is not None and not resolved_page:
                resolved_page = await _resolved_whatsapp_page(db, row)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - redirect regardless
            await db.rollback()
            logger.error(
                "track_whatsapp_click_failed",
                tracking_uuid=tracking_uuid,
                error=str(exc),
            )
    # Always redirect to the configured public origin.  A Host / X-Forwarded-Host
    # header is attacker-controlled and would otherwise turn these tracking
    # links into an open redirect to any domain.
    base_url = settings.base_url.rstrip("/")
    target = f"{base_url}/whatsapp-lure/{tracking_uuid}"
    if resolved_page:
        target = f"{target}?page={quote(resolved_page, safe='')}"
    logger.info(
        "whatsapp_click_redirect",
        tracking_uuid=tracking_uuid,
        landing_page=resolved_page,
        target=target,
    )
    return RedirectResponse(
        url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS
    )


async def _resolved_whatsapp_page(
    db: AsyncSession, tracking: EmailTracking
) -> str | None:
    """Resolve the lure skin for one WhatsApp tracking row."""
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    raw_config = campaign.channel_config if campaign is not None else None
    config = raw_config if isinstance(raw_config, dict) else {}
    block = config.get("whatsapp")
    if not isinstance(block, dict):
        block = config.get("sms") if isinstance(config.get("sms"), dict) else {}
    template = (
        await db.get(EmailTemplate, tracking.template_id)
        if tracking.template_id
        else None
    )
    employee = (
        await db.get(HumanAsset, tracking.employee_id)
        if tracking.employee_id
        else None
    )
    message = str(block.get("custom_message") or "")
    if not message and template is not None:
        message = str(template.subject or "") + " " + str(template.body_html or "")
    return LandingPageResolver().resolve(
        message=message,
        department=getattr(employee, "department", None) if employee else None,
        manual=block.get("selected_landing_page"),
    )


@router.post(
    "/sms/submit",
    summary="SMS landing submission (-40 Elo, applied once)",
)
async def track_sms_submit(
    request: Request,
    payload: dict | None = Body(default=None),
    tracking_uuid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Record a credential submission on the SMS landing page.

    The ``tracking_uuid`` may be sent in the JSON body (``{"tracking_uuid":
    "…"}``) or as a query parameter.  Submission is idempotent: the first one
    applies ``-40`` Elo and later ones only return the current state.

    Returns:
        The outcome, the refreshed Elo score and the training-page redirect.
    """
    settings = get_settings()
    body_uid = None
    if isinstance(payload, dict):
        body_uid = payload.get("tracking_uuid")
    uid = str(body_uid or tracking_uuid or "").strip()
    if not _valid_uuid(uid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tracking_uuid is required",
        )

    # The landing form posts the identifier it collected plus the password, which
    # is reduced to its length here and never persisted.
    body_identifier = ""
    body_password = ""
    if isinstance(payload, dict):
        for key in ("identifier", "email", "username"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                body_identifier = value.strip()
                break
        password_value = payload.get("password")
        if isinstance(password_value, str):
            body_password = password_value
    result = await TrackingService().log_sms_submission(
        uid,
        _client_ip(request),
        request.headers.get("user-agent"),
        db,
        identifier=body_identifier or None,
        password_length=len(body_password) or None,
    )
    if result is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tracking link not found"
        )
    row, already_recorded = result
    employee = await db.get(HumanAsset, row.employee_id)
    await db.commit()

    # Always redirect to the configured public origin.  A Host / X-Forwarded-Host
    # header is attacker-controlled and would otherwise turn these tracking
    # links into an open redirect to any domain.
    base_url = settings.base_url.rstrip("/")
    return {
        "success": True,
        "tracking_uuid": uid,
        "already_recorded": already_recorded,
        "elo_score": employee.elo_score if employee is not None else None,
        "elo_delta": 0 if already_recorded else -40,
        "redirect_url": f"{base_url}/training/{uid}?channel=sms",
    }


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
    """Record a simulated credential-form submission.

    For a QR/quishing row the endpoint is intentionally secret-free: the
    password value is discarded before storage, only the identifier, password
    length and non-secret field names are retained, and the first submission
    applies the -25 quishing penalty exactly once.  Other channels preserve the
    encrypted-payload behaviour.

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
            capture_secret=payload.capture_secret,
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
    "/otp/{tracking_uuid}",
    response_model=TrainingInteractionResponse,
    summary="Submit 6-digit verification code (OTP / MFA bypass)",
)
async def track_otp(
    tracking_uuid: str,
    payload: OTPVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TrainingInteractionResponse:
    """Record an MFA / OTP bypass attempt from the simulated landing page.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        payload: The submitted OTP code.
        request: Incoming HTTP request (for IP/User-Agent).
        db: Active database session.

    Returns:
        TrainingInteractionResponse with status.
    """
    if not _valid_uuid(tracking_uuid):
        return TrainingInteractionResponse(
            success=False, message="Invalid tracking identifier"
        )
    try:
        row = await TrackingService().log_otp_submission(
            tracking_uuid,
            payload.otp_code,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
        )
        if row is None:
            await db.rollback()
            return TrainingInteractionResponse(
                success=False, message="Tracking record not found"
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("track_otp_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrainingInteractionResponse(
            success=False, message="Unable to record OTP submission"
        )
    return TrainingInteractionResponse(
        success=True,
        first_time=True,
        message="OTP verification recorded.",
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
    "/visit/{tracking_uuid}",
    response_model=TrainingInteractionResponse,
    summary="Record a neutral visit to a simulation page",
)
async def track_visit(
    tracking_uuid: str,
    request: Request,
    channel: str = Query("vishing", pattern="^(qr|vishing|pretexting)$"),
    db: AsyncSession = Depends(get_db),
) -> TrainingInteractionResponse:
    """Record that a recipient opened a vishing/pretexting simulation page.

    This is deliberately score-neutral.  The outcome endpoint applies the
    channel-specific Elo rule only after the recipient makes a choice.
    """
    if not _valid_uuid(tracking_uuid):
        return TrainingInteractionResponse(
            success=False, message="Invalid tracking identifier"
        )
    try:
        row = await TrackingService().log_channel_visit(
            tracking_uuid,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
            channel=channel,
        )
        if row is None:
            await db.rollback()
            return TrainingInteractionResponse(
                success=False, message="Tracking record not found"
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - never break the page
        await db.rollback()
        logger.error("track_visit_failed", tracking_uuid=tracking_uuid, error=str(exc))
        return TrainingInteractionResponse(success=False, message="Unable to record the visit")
    return TrainingInteractionResponse(success=True, message="Visit recorded.")


@router.post(
    "/qr/probe",
    response_model=QRProbeResponse,
    dependencies=[Depends(rate_limit(limit=60, window=60, scope="qr_probe"))],
    summary="Record immediate background hardware & network telemetry from landing page",
)
async def track_qr_probe(
    payload: QRProbeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> QRProbeResponse:
    """Capture rich client-side forensic telemetry immediately upon landing."""
    try:
        await TrackingService().record_qr_probe(
            db,
            campaign_id=payload.campaign_id,
            tracking_uuid=payload.tracking_uuid,
            fingerprint_data=payload.fingerprint_data,
            telemetry=payload.telemetry,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
        return QRProbeResponse(success=True, status="ok", message="Telemetry recorded")
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning("track_qr_probe_failed", error=str(exc))
        return QRProbeResponse(success=False, status="error", message=str(exc))


@router.post(
    "/qr/submit",
    response_model=QRSubmissionResponse,
    dependencies=[Depends(rate_limit(limit=10, window=60, scope="qr_submit"))],
    summary="Record a QR/quishing credential submission and resolve identity",
)
async def track_qr_submit(
    payload: QRSubmissionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> QRSubmissionResponse:
    """Record a quishing form submission.

    The typed password is never accepted into storage: the request schema
    ignores it and only ``password_submitted`` is retained.  The entered
    username/e-mail are matched against ``human_assets`` (e-mail first, then
    username/employee number) and the once-only -25 Elo penalty is applied.
    Unknown identities are stored as an Unknown scan with their device
    fingerprint so an administrator can assign them later.
    """
    try:
        merged_fp = dict(payload.fingerprint_data or {})
        if payload.telemetry:
            merged_fp.update(payload.telemetry)
            if "telemetry" not in merged_fp:
                merged_fp["telemetry"] = payload.telemetry

        result = await TrackingService().submit_qr_scan(
            db,
            campaign_id=payload.campaign_id,
            username=payload.username,
            email=payload.email,
            password_submitted=bool(payload.password_submitted),
            fields=payload.fields,
            fingerprint_data=merged_fp,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            tracking_uuid=payload.tracking_uuid,
            client=payload.telemetry or None,
        )
        if result is None:
            await db.rollback()
            return QRSubmissionResponse(
                success=False, message="Campaign or tracking link not found"
            )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - never break the landing page
        await db.rollback()
        logger.error("track_qr_submit_failed", error=str(exc))
        return QRSubmissionResponse(
            success=False, status="error", message="Unable to record the submission"
        )

    employee = result.employee
    tracking_uuid = (
        result.tracking.tracking_uuid if result.tracking is not None else None
    )
    redirect_url = f"/training/{tracking_uuid}?channel=qr" if tracking_uuid else f"/training/{payload.campaign_id}?channel=qr"
    return QRSubmissionResponse(
        success=True,
        status="success",
        redirect=redirect_url,
        redirect_url=redirect_url,
        first_time=result.first_time,
        unknown=employee is None,
        message=(
            "بياناتك قيد المراجعة."
            if employee is None
            else "تم التحقق من بياناتك بنجاح."
        ),
        identity_resolution=result.identity_resolution,
        # Public endpoint: never echo the matched employee's identity back.
        # The campaign UUID is printed on a poster, so returning the name would
        # turn this route into a staff-address enumeration oracle.  The redirect
        # carries the per-recipient tracking UUID instead.
        resolved_employee_id=None,
        resolved_employee_name=None,
        tracking_uuid=tracking_uuid,
        elo_delta=result.elo_delta,
        elo_score=(
            int(employee.elo_score) if employee is not None and employee.elo_score is not None else None
        ),
    )


def _qr_branding_payload(
    config: dict, organization: Organization
) -> dict[str, object]:
    """Resolve the public QR branding payload for a campaign/organization."""
    branding = branding_from_organization(organization, get_settings().base_url)
    poster = resolve_poster_copy(
        config,
        company_name=organization.name,
        department="",
        primary_color=branding.primary_color,
        logo=organization.brand_logo_data,
    )
    qr_config = config.get("qr")
    logo_data_url = (
        qr_config.get("logo_data_url") if isinstance(qr_config, dict) else None
    )
    return {
        "lure_type": poster.lure_type,
        "company_name": poster.company_name,
        "department": poster.department,
        "month_label": poster.month_label,
        "label": poster.label,
        "headline": poster.headline,
        "body": poster.body,
        "cta": poster.cta,
        "primary_color": poster.primary_color,
        "accent_color": poster.accent_color,
        "logo_url": logo_data_url or branding.logo_url,
    }


@router.get(
    "/qr/campaign/{campaign_id}/context",
    summary="Public context for a generic QR campaign poster",
)
async def qr_campaign_context(
    campaign_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return the branding/lure context for a generic (no-recipient) poster.

    The campaign UUID is printed on the poster, so it is public by design.  No
    employee data is ever returned.
    """
    if not _valid_uuid(campaign_id):
        return {"found": False}
    campaign = await db.get(EmailCampaign, uuid.UUID(campaign_id))
    if campaign is None or (campaign.channel or "").strip().lower() != "qr":
        return {"found": False}
    organization = await db.get(Organization, campaign.organization_id)
    if organization is None:  # pragma: no cover - FK guarantees existence
        return {"found": False}
    config = campaign.channel_config or {}
    effective_base_url = get_settings().base_url.rstrip("/")
    branding = branding_from_organization(organization, effective_base_url)
    return {
        "found": True,
        "campaign_id": str(campaign.id),
        "campaign_name": campaign.name,
        "company_name": organization.name,
        "channel": "qr",
        "channel_config": config,
        "qr_branding": _qr_branding_payload(config, organization),
        "brand_primary_color": branding.primary_color,
        "brand_logo_url": branding.logo_url,
    }


@router.get(
    "/qr/{campaign_id}",
    summary="Quishing scan tracker (302 to the matching lure landing page)",
)
async def track_qr_scan(
    campaign_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Log a QR scan in tracking_events and redirect to /qr/landing/{campaign_id}.

    Captures IP address and User-Agent telemetry, logs the scan event, and
    redirects the visitor to the generic lure landing page.
    """
    settings = get_settings()
    # Always redirect to the configured public origin.  A Host / X-Forwarded-Host
    # header is attacker-controlled and would otherwise turn these tracking
    # links into an open redirect to any domain.
    base_url = settings.base_url.rstrip("/")
    target_suffix = f"/qr/hr/{campaign_id}"
    tracking_uuid = campaign_id

    if _valid_uuid(campaign_id):
        identifier = uuid.UUID(campaign_id)
        campaign = await db.get(EmailCampaign, identifier)
        if campaign is not None and (campaign.channel or "").strip().lower() == "qr":
            try:
                tracking_row, scan_row = await TrackingService().log_campaign_qr_scan(
                    campaign,
                    _client_ip(request),
                    request.headers.get("user-agent"),
                    db,
                )
                await db.commit()
                config = campaign.channel_config or {}
                qr_config = config.get("qr")
                qr_values = dict(qr_config) if isinstance(qr_config, dict) else {}
                lure_type = normalize_lure_type(qr_values.get("lure_type") or qr_values.get("pretext_key")) or "bonus"
                target_suffix = f"/qr/landing/{campaign.id}?tid={tracking_row.tracking_uuid}"
            except Exception as exc:
                await db.rollback()
                logger.error("track_qr_campaign_scan_failed", error=str(exc))
                target_suffix = f"/qr/landing/{campaign.id}"
        else:
            try:
                row = await TrackingService().log_qr_scan(
                    tracking_uuid,
                    _client_ip(request),
                    request.headers.get("user-agent"),
                    db,
                )
                await db.commit()
                if row is not None:
                    campaign = await db.get(EmailCampaign, row.campaign_id)
                    config = (
                        campaign.channel_config if campaign is not None else None
                    ) or {}
                    qr_config = config.get("qr")
                    qr_values = (
                        dict(qr_config) if isinstance(qr_config, dict) else {}
                    )
                    lure_type = normalize_lure_type(
                        qr_values.get("lure_type") or qr_values.get("pretext_key")
                    )
                    target_suffix = f"/qr/{lure_type}/{tracking_uuid}"
            except Exception as exc:  # noqa: BLE001 - redirect regardless
                await db.rollback()
                logger.error(
                    "track_qr_failed", tracking_uuid=tracking_uuid, error=str(exc)
                )

    target = f"{base_url}{target_suffix}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS)


@router.get(
    "/usb/{tracking_uuid}",
    summary="USB document open tracker (302 to the USB training page)",
)
async def track_usb_open(
    tracking_uuid: str,
    request: Request,
    hostname: str | None = None,
    username: str | None = None,
    domain: str | None = None,
    arch: str | None = None,
    scenario: str | None = None,
    attack_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Log a safe USB-document open, apply the Elo penalty and redirect.

    The first open is a USB-specific failure.  Repeated opens are still recorded
    in the ledger for evidence but do not change the Elo score again.  A row
    that belongs to another channel is never penalised through this URL.
    """
    settings = get_settings()
    channel = "usb"
    if _valid_uuid(tracking_uuid):
        try:
            row = await TrackingService().log_usb_open(
                tracking_uuid,
                _client_ip(request),
                request.headers.get("user-agent"),
                db,
                hostname=hostname,
                username=username,
                domain=domain,
                arch=arch,
                scenario=scenario,
                attack_type=attack_type,
            )
            await db.commit()
            if row is not None:
                channel = (row.channel or "usb").strip().lower() or "usb"
        except Exception as exc:  # noqa: BLE001 - redirect regardless
            await db.rollback()
            logger.error("track_usb_failed", tracking_uuid=tracking_uuid, error=str(exc))
    target = f"{settings.base_url.rstrip('/')}/training/{tracking_uuid}?channel={channel}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS)


#: A USB document runs from ``file://``, whose Origin is the literal string
#: ``null``.  The beacon response therefore allows any origin and never asks for
#: credentials — the tracking UUID in the path is the only secret.
USB_BEACON_HEADERS = {
    **NO_CACHE_HEADERS,
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}

#: No document needs to send more than this; anything larger is truncated.
MAX_USB_TELEMETRY_BYTES = 32_768


def _usb_beacon_payload(**fields: object) -> JSONResponse:
    """Return the small JSON body the document reads back, CORS-safe."""
    return JSONResponse(content=fields, headers=USB_BEACON_HEADERS)


def _decode_telemetry(raw: bytes) -> dict[str, object]:
    """Best-effort decode of a beacon body.

    The document posts a JSON string with ``Content-Type: text/plain`` so the
    request stays *simple* (no CORS preflight from ``file://``).  Form-encoded
    submissions are also accepted for older copies of the document that send
    ``payload=<json>``.
    """
    if not raw:
        return {}
    body = raw[:MAX_USB_TELEMETRY_BYTES]
    try:
        decoded = json.loads(body.decode("utf-8", "ignore"))
    except (ValueError, UnicodeDecodeError):
        decoded = None
    if isinstance(decoded, dict):
        return decoded
    try:
        form = parse_qs(body.decode("utf-8", "ignore"))
    except (ValueError, UnicodeDecodeError):
        return {}
    for key in ("payload", "telemetry", "data"):
        candidate = (form.get(key) or [""])[0]
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


@router.options("/usb/{tracking_uuid}", include_in_schema=False)
async def track_usb_preflight(tracking_uuid: str) -> Response:
    """Answer the CORS preflight a browser may still send for the beacon."""
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=USB_BEACON_HEADERS)


@router.post(
    "/usb/{tracking_uuid}",
    summary="USB document forensic telemetry beacon",
)
async def track_usb_telemetry(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Record a USB-document open together with the full device profile.

    The document is opened from a USB stick, so this endpoint must work from
    ``file://`` with no cookies and no preflight.  It accepts the forensic packet
    the document collects (device, screen, GPU, network, timezone, the full
    ``file:///`` source path, optional GPS), enriches it with the server-observed
    address, GeoIP and a parsed device model, and writes one ``usb_opened``
    ledger row — even when the campaign has no employee attached, which is the
    normal case for a physical drop.

    Returns:
        ``{"ok": bool, "recorded": bool, ...}``; the document only reads ``ok``
        to decide whether it must queue the packet for a later retry.
    """
    telemetry = sanitize_telemetry(_decode_telemetry(await request.body()))
    if not _valid_uuid(tracking_uuid):
        return _usb_beacon_payload(ok=False, recorded=False, reason="invalid_tracking_id")

    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent")
    device = telemetry.get("device")
    device = device if isinstance(device, dict) else {}

    try:
        geo = await lookup_ip_geolocation(ip_address)
    except Exception as exc:  # noqa: BLE001 - geo lookup must never block the open
        logger.warning("usb_geo_lookup_failed", error=str(exc))
        geo = None

    telemetry["server"] = {
        "ip": ip_address,
        "country": getattr(geo, "country", None),
        "city": getattr(geo, "city", None),
        "isp": getattr(geo, "isp", None),
        "latitude": getattr(geo, "latitude", None),
        "longitude": getattr(geo, "longitude", None),
        "device_model": detect_device_model(
            user_agent,
            fingerprint_data=telemetry,
        ),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    telemetry["server"] = {
        key: value for key, value in telemetry["server"].items() if value not in (None, "")
    }

    recorded = False
    try:
        row = await TrackingService().log_usb_open(
            tracking_uuid,
            ip_address,
            user_agent,
            db,
            hostname=device.get("hostname"),
            username=device.get("username"),
            domain=device.get("domain"),
            arch=device.get("ua_architecture"),
            scenario=device.get("os") or device.get("platform"),
            attack_type="baiting",
            telemetry=telemetry,
        )
        await db.commit()
        recorded = row is not None
    except Exception as exc:  # noqa: BLE001 - the warning page must never break
        await db.rollback()
        logger.error(
            "track_usb_telemetry_failed",
            tracking_uuid=tracking_uuid,
            error=str(exc),
        )
        return _usb_beacon_payload(ok=False, recorded=False, reason="storage_error")

    logger.info(
        "usb_telemetry_received",
        tracking_uuid=tracking_uuid,
        recorded=recorded,
        ip_address=ip_address,
        platform=device.get("ua_platform"),
        city=getattr(geo, "city", None),
        source_path=(telemetry.get("source") or {}).get("path"),
    )
    settings = get_settings()
    return _usb_beacon_payload(
        ok=recorded,
        recorded=recorded,
        tracking_uuid=tracking_uuid,
        training_url=f"{settings.base_url.rstrip('/')}/training/{tracking_uuid}?channel=usb",
        server_time=datetime.now(timezone.utc).isoformat(),
    )


@router.options("/usb/{tracking_uuid}/device", include_in_schema=False)
async def track_usb_device_preflight(tracking_uuid: str) -> Response:
    """Answer the preflight for the local identity tool's POST."""
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=USB_BEACON_HEADERS)


@router.post(
    "/usb/{tracking_uuid}/device",
    summary="Local identity tool report (Windows account and machine name)",
)
async def track_usb_device_probe(
    tracking_uuid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Attach the Windows account and real machine name to a USB open.

    A ``file://`` page is denied both values by the browser.  The optional
    collector the operator copies to the stick reads them and posts them here.
    The endpoint is public exactly like the beacon (the tracking UUID is the
    only secret), so the stored shape is a fixed whitelist and the call never
    raises: the script's offline queue depends on a truthful ``ok``.
    """
    payload = _decode_telemetry(await request.body())
    if not _valid_uuid(tracking_uuid):
        return _usb_beacon_payload(ok=False, recorded=False, reason="invalid_tracking_id")

    try:
        row, recorded = await TrackingService().log_usb_device_probe(
            tracking_uuid,
            payload,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - the collector must never see a 500
        await db.rollback()
        logger.error(
            "track_usb_device_probe_failed",
            tracking_uuid=tracking_uuid,
            error=str(exc),
        )
        return _usb_beacon_payload(ok=False, recorded=False, reason="storage_error")

    logger.info(
        "usb_device_probe_received",
        tracking_uuid=tracking_uuid,
        recorded=recorded,
        identity_source="local_tool" if recorded else None,
    )
    return _usb_beacon_payload(
        ok=recorded,
        recorded=recorded,
        duplicate=row is not None and not recorded,
        tracking_uuid=tracking_uuid,
        server_time=datetime.now(timezone.utc).isoformat(),
    )


async def _record_simulation_choice(
    tracking_uuid: str,
    channel: str,
    payload: SimulationChoiceRequest,
    request: Request,
    db: AsyncSession,
) -> SimulationChoiceResponse:
    """Shared implementation for the vishing/pretexting choice endpoints."""
    if not _valid_uuid(tracking_uuid):
        return SimulationChoiceResponse(
            success=False, choice=payload.choice, message="Invalid tracking identifier"
        )
    try:
        result = await TrackingService().log_channel_choice(
            tracking_uuid,
            channel,
            payload.choice,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
            client={"choice": payload.choice, "channel": channel},
        )
        if result is None:
            await db.rollback()
            return SimulationChoiceResponse(
                success=False,
                choice=payload.choice,
                message="تعذّر العثور على رابط المحاكاة.",
            )
        row, already_recorded = result
        employee = await db.get(HumanAsset, row.employee_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - never break the simulation page
        await db.rollback()
        logger.error(
            "track_simulation_choice_failed",
            tracking_uuid=tracking_uuid,
            channel=channel,
            error=str(exc),
        )
        return SimulationChoiceResponse(
            success=False,
            choice=payload.choice,
            message="تعذّر تسجيل الاختيار. أعد المحاولة.",
        )
    settings = get_settings()
    return SimulationChoiceResponse(
        success=True,
        choice=payload.choice,
        already_recorded=already_recorded,
        message=(
            "تم تسجيل هذا الاختيار مسبقاً."
            if already_recorded
            else "تم تسجيل اختيارك بنجاح."
        ),
        elo_score=int(employee.elo_score) if employee and employee.elo_score is not None else None,
        threat_level=threat_level_for_elo(employee.elo_score) if employee else None,
        redirect_url=f"{settings.base_url.rstrip('/')}/training/{tracking_uuid}?channel={channel}",
    )


@router.post(
    "/vishing/{tracking_uuid}",
    response_model=SimulationChoiceResponse,
    summary="Record a vishing simulation choice",
)
async def track_vishing_choice(
    tracking_uuid: str,
    payload: SimulationChoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SimulationChoiceResponse:
    """Record ``credential_disclosed`` (-30 Elo) or ``reported_phish`` (+20)."""
    return await _record_simulation_choice(
        tracking_uuid, "vishing", payload, request, db
    )


@router.post(
    "/pretexting/{tracking_uuid}",
    response_model=SimulationChoiceResponse,
    summary="Record a pretexting simulation choice",
)
async def track_pretexting_choice(
    tracking_uuid: str,
    payload: SimulationChoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SimulationChoiceResponse:
    """Record ``financial_fraud`` (-30 Elo) or ``reported_phish`` (+20)."""
    return await _record_simulation_choice(
        tracking_uuid, "pretexting", payload, request, db
    )


@router.post(
    "/ceo/{tracking_uuid}",
    response_model=SimulationChoiceResponse,
    summary="Record a CEO-pretexting simulation choice (alias)",
)
async def track_ceo_choice(
    tracking_uuid: str,
    payload: SimulationChoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SimulationChoiceResponse:
    """Alias for the CEO-pretexting page at ``/simulation/ceo/{uuid}``."""
    return await _record_simulation_choice(
        tracking_uuid, "pretexting", payload, request, db
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
