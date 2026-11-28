"""Real outbound vishing calls through the IllyVoIP Voice API.

These endpoints never simulate a call.  A request either reaches IllyVoIP or
fails with a typed provider error.  Campaign calls are correlated through the
existing ``tracking_events`` row and the IllyVoIP ``call_control_id`` so the
normal reporting funnel, interaction ledger and employee counters continue to
work.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    Organization,
    User,
)
from app.schemas import (
    VishingCallRequest,
    VishingCallResponse,
    VishingCallStatusResponse,
    VishingConfigResponse,
    VishingHangupResponse,
)
from app.services.illyvoip_service import (
    IllyVoIPAPIError,
    IllyVoIPCallFailedError,
    IllyVoIPConfigurationError,
    IllyVoIPContentReviewError,
    IllyVoIPError,
    IllyVoIPService,
    IllyVoIPTimeoutError,
    IllyVoIPTransportError,
    IllyVoIPValidationError,
    is_e164_phone,
    mask_phone,
)
from app.services.tracking_service import (
    EVENT_VISHING_CALL_ANSWERED,
    EVENT_VISHING_CALL_COMPLETED,
    EVENT_VISHING_CALL_FAILED,
    EVENT_VISHING_CALL_PLACED,
    EVENT_VISHING_TTS_PLAYED,
    TrackingService,
)

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/vishing",
    tags=["vishing"],
    dependencies=[Depends(rate_limit(scope="vishing"))],
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _employee_phone(employee: HumanAsset) -> str:
    """Return an employee's E.164 phone or raise an actionable 400."""
    phone = (employee.phone or "").strip()
    if not is_e164_phone(phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "employee phone must be in E.164 format (for example "
                "+966500000000); update the employee record first"
            ),
        )
    return phone


async def _get_employee(
    db: AsyncSession, org_id: uuid.UUID, employee_id: uuid.UUID
) -> HumanAsset:
    employee = await db.get(HumanAsset, employee_id)
    if employee is None or employee.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    if not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee is inactive and cannot be called",
        )
    return employee


async def _resolve_target(
    db: AsyncSession,
    org_id: uuid.UUID,
    payload: VishingCallRequest,
    user: User,
) -> tuple[
    EmailCampaign | None,
    EmailTracking | None,
    HumanAsset | None,
    str,
    bool,
]:
    """Resolve the campaign, tracking row, employee and destination.

    Returns ``(campaign, tracking, employee, phone, tracking_created)``.  The
    tracking row is created only when a campaign and employee are both known;
    an ad-hoc administrator smoke call has no campaign row to attach to.
    """
    campaign: EmailCampaign | None = None
    if payload.campaign_id is not None:
        campaign = await db.get(EmailCampaign, payload.campaign_id)
        if campaign is None or campaign.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found",
            )

    tracking: EmailTracking | None = None
    if payload.tracking_uuid is not None:
        tracking = await db.scalar(
            select(EmailTracking).where(
                EmailTracking.tracking_uuid == payload.tracking_uuid
            )
        )
        if tracking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking record not found",
            )
        if campaign is not None and tracking.campaign_id != campaign.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking record does not belong to the campaign",
            )
        if campaign is None:
            campaign = await db.get(EmailCampaign, tracking.campaign_id)
            if campaign is None or campaign.organization_id != org_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Campaign not found",
                )

    # ``voice`` is the real-call campaign channel; ``vishing`` is the manual
    # browser simulation.  Both can carry a real outbound call.
    if campaign is not None and (campaign.channel or "").strip().lower() not in {
        "vishing",
        "voice",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign channel is not vishing or voice",
        )

    employee: HumanAsset | None = None
    if payload.employee_id is not None:
        employee = await _get_employee(db, org_id, payload.employee_id)
    elif tracking is not None and tracking.employee_id is not None:
        employee = await _get_employee(db, org_id, tracking.employee_id)

    if (
        tracking is not None
        and employee is not None
        and tracking.employee_id is not None
        and tracking.employee_id != employee.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tracking record does not belong to the selected employee",
        )

    if employee is not None:
        phone = _employee_phone(employee)
    else:
        if user.role.lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Only administrators can place a call to an arbitrary "
                    "number; use employee_id for campaign recipients"
                ),
            )
        candidate = (payload.to_phone or "").strip()
        if not is_e164_phone(candidate):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "to_phone must be in E.164 format (for example "
                    "+966500000000)"
                ),
            )
        phone = candidate

    tracking_created = False
    if campaign is not None and employee is not None and tracking is None:
        tracking = await db.scalar(
            select(EmailTracking).where(
                EmailTracking.campaign_id == campaign.id,
                EmailTracking.employee_id == employee.id,
            )
        )
        if tracking is None:
            tracking = EmailTracking(
                campaign_id=campaign.id,
                employee_id=employee.id,
                template_id=campaign.template_id,
                # Keep the row on the campaign's own channel so a real
                # ``voice`` campaign is not reported as a manual simulation.
                channel=(campaign.channel or "vishing").strip().lower(),
                provider="illyvoip",
                tracking_uuid=uuid.uuid4(),
            )
            db.add(tracking)
            await db.flush()
            tracking_created = True

    if campaign is not None and tracking is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="campaign calls require employee_id or tracking_uuid",
        )

    return campaign, tracking, employee, phone, tracking_created


async def _record_event(
    db: AsyncSession,
    tracking: EmailTracking | None,
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
    provider_message_id: str | None = None,
    delivery_status: str | None = None,
    delivery_error: str | None = None,
) -> None:
    """Append one audit event without letting a ledger failure hide the call."""
    if tracking is None:
        return
    try:
        async with db.begin_nested():
            await TrackingService().log_vishing_event(
                tracking.tracking_uuid,
                event_type,
                db,
                details=details,
                provider_message_id=provider_message_id,
                delivery_status=delivery_status,
                delivery_error=delivery_error,
            )
    except Exception:  # noqa: BLE001 - the provider call already happened
        logger.exception(
            "vishing_audit_event_failed",
            tracking_uuid=str(tracking.tracking_uuid),
            event_type=event_type,
        )


def _call_details(result: dict[str, Any]) -> dict[str, Any]:
    """Build non-secret details for the interaction ledger."""
    return {
        "provider": "illyvoip",
        "call_control_id": result.get("call_control_id"),
        "state": result.get("state"),
        "call_status": result.get("call_status"),
        "duration_seconds": result.get("duration_seconds"),
        "tts_media": result.get("tts_media"),
        "answered_at": result.get("answered_at"),
        "ended_at": result.get("ended_at"),
        "failure_reason": result.get("failure_reason"),
        # Whether the destination rang, and whether the answer looked automatic.
        "rang": bool(result.get("rang")),
        "answer_delay_seconds": result.get("answer_delay_seconds"),
        "answer_suspect_auto": bool(result.get("answer_suspect_auto")),
    }


async def _persist_success(
    db: AsyncSession,
    tracking: EmailTracking | None,
    result: dict[str, Any],
    employee: HumanAsset | None,
    *,
    count_test: bool,
) -> None:
    """Persist a completed call and its audit events."""
    call_id = str(result.get("call_control_id") or "")
    details = _call_details(result)
    if tracking is not None:
        # Record "answered" only when the destination actually rang and the
        # answer did not look automatic: an answered session alone can be a
        # voicemail, an IVR or a carrier announcement.
        answered_with_evidence = bool(
            result.get("answered_at")
            and result.get("rang")
            and not result.get("answer_suspect_auto")
        )
        if answered_with_evidence:
            await _record_event(
                db,
                tracking,
                EVENT_VISHING_CALL_ANSWERED,
                details=details,
                provider_message_id=call_id or None,
                delivery_status="answered",
            )
        if result.get("tts_media"):
            await _record_event(
                db,
                tracking,
                EVENT_VISHING_TTS_PLAYED,
                details={
                    "call_control_id": call_id,
                    "tts_media": result.get("tts_media"),
                    "tts_charge": result.get("tts_charge"),
                },
                provider_message_id=call_id or None,
                delivery_status="answered",
            )
        await _record_event(
            db,
            tracking,
            EVENT_VISHING_CALL_COMPLETED,
            details=details,
            provider_message_id=call_id or None,
            delivery_status="completed",
        )
        tracking.provider = "illyvoip"
        if call_id:
            tracking.provider_message_id = call_id[:255]
        tracking.delivery_status = "completed"
        tracking.delivery_error = None
        now = _now()
        tracking.sent_at = tracking.sent_at or now
        tracking.delivered_at = tracking.delivered_at or now
        tracking.completed_at = tracking.completed_at or now

    if employee is not None and count_test:
        employee.total_tests_received = (employee.total_tests_received or 0) + 1
        employee.last_test_date = _now()

    await db.commit()


async def _persist_failure(
    db: AsyncSession,
    tracking: EmailTracking | None,
    exc: IllyVoIPError,
) -> None:
    """Persist a failed call attempt and its audit event."""
    call_id = str(exc.fields.get("call_control_id") or "") or None
    if tracking is not None:
        await _record_event(
            db,
            tracking,
            EVENT_VISHING_CALL_FAILED,
            details={
                "provider": "illyvoip",
                "error": str(exc),
                "error_code": exc.error_code,
                "provider_status_code": exc.status_code,
                "call_control_id": call_id,
            },
            provider_message_id=call_id,
            delivery_status="failed",
            delivery_error=str(exc),
        )
        tracking.provider = "illyvoip"
        if call_id:
            tracking.provider_message_id = call_id[:255]
        tracking.delivery_status = "failed"
        tracking.delivery_error = str(exc)[:500]
        tracking.failed_at = tracking.failed_at or _now()
    await db.commit()


def _provider_http_error(exc: IllyVoIPError) -> HTTPException:
    """Map a typed provider error to an actionable HTTP response."""
    if isinstance(exc, IllyVoIPContentReviewError):
        return HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "error_code": exc.error_code,
                "review_reference": exc.review_reference,
                "hint": (
                    "The text was refused by IllyVoIP content review and was "
                    "not charged or played. Resolve it in the Communication "
                    "reviews screen, then retry with a new idempotency key."
                ),
            },
        )
    if isinstance(exc, IllyVoIPConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": str(exc),
                "error_code": exc.error_code or "illyvoip_not_configured",
                "hint": (
                    "Set ILLYVOIP_API_KEY in backend/.env, then restart the "
                    "API. ILLYVOIP_SIP_USER_ID and ILLYVOIP_CALLER_ID are "
                    "optional; IllyVoIP then uses the account defaults."
                ),
            },
        )
    if isinstance(exc, IllyVoIPValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "error_code": exc.error_code},
        )
    if isinstance(exc, IllyVoIPTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "message": str(exc),
                "error_code": exc.error_code or "illyvoip_timeout",
            },
        )
    if isinstance(exc, IllyVoIPCallFailedError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": str(exc),
                "error_code": exc.error_code or "call_not_answered",
                "failure_reason": (
                    exc.fields.get("status", {}).get("failure_reason")
                    if isinstance(exc.fields.get("status"), dict)
                    else None
                ),
            },
        )
    if isinstance(exc, IllyVoIPTransportError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": str(exc),
                "error_code": "illyvoip_transport_error",
                "retryable": True,
            },
        )
    if isinstance(exc, IllyVoIPAPIError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": str(exc),
                "error_code": exc.error_code,
                "provider_status_code": exc.status_code,
                "retryable": exc.retryable,
                "retry_after": exc.retry_after,
            },
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"message": str(exc), "error_code": exc.error_code},
    )


async def _tracking_for_call(
    db: AsyncSession, org_id: uuid.UUID, call_control_id: str
) -> EmailTracking:
    """Find the campaign tracking row that owns ``call_control_id``."""
    tracking = await db.scalar(
        select(EmailTracking)
        .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
        .where(
            EmailTracking.provider_message_id == call_control_id,
            EmailCampaign.organization_id == org_id,
        )
    )
    if tracking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found for this organization",
        )
    return tracking


# --------------------------------------------------------------------------- #
# Configuration and diagnostics
# --------------------------------------------------------------------------- #
@router.get(
    "/config",
    response_model=VishingConfigResponse,
    summary="Read non-secret IllyVoIP vishing readiness",
)
async def get_vishing_config(
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager", "viewer")),
) -> VishingConfigResponse:
    """Return local configuration readiness without calling the provider."""
    return VishingConfigResponse(**IllyVoIPService().configuration_status())


@router.get(
    "/verify",
    response_model=VishingConfigResponse,
    summary="Verify the live IllyVoIP Voice API",
)
async def verify_vishing_config(
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> VishingConfigResponse:
    """Call the IllyVoIP Voice backend status endpoint (no call is placed)."""
    result = await IllyVoIPService().verify_configuration()
    return VishingConfigResponse(**result)


# --------------------------------------------------------------------------- #
# Call control
# --------------------------------------------------------------------------- #
@router.post(
    "/calls",
    response_model=VishingCallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place one real outbound vishing call",
)
async def place_vishing_call(
    payload: VishingCallRequest,
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
    db: AsyncSession = Depends(get_db),
) -> VishingCallResponse:
    """Create, answer, speak through native TTS, wait and hang up one call.

    This is a synchronous control flow: the request stays open while the
    recipient answers and the prompt plays.  Use the campaign Celery task for
    bulk campaigns so the HTTP request is not held for every recipient.
    """
    if not payload.confirm_authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "confirm_authorized must be true; only call employees or test "
                "numbers you are authorised to contact"
            ),
        )

    campaign, tracking, employee, phone, tracking_created = await _resolve_target(
        db, organization.id, payload, user
    )
    settings = get_settings()

    if tracking is not None:
        await _record_event(
            db,
            tracking,
            EVENT_VISHING_CALL_PLACED,
            details={
                "provider": "illyvoip",
                "script_characters": len(payload.script),
                "language": payload.language or settings.illyvoip_tts_language,
                "voice": payload.voice or settings.illyvoip_tts_voice,
                "record": bool(
                    settings.illyvoip_record_calls
                    if payload.record is None
                    else payload.record
                ),
            },
            delivery_status="calling",
        )
        await db.commit()

    service = IllyVoIPService(settings=settings)
    try:
        result = await service.place_vishing_call(
            phone,
            payload.script,
            campaign_id=campaign.id if campaign is not None else None,
            tracking_uuid=tracking.tracking_uuid if tracking is not None else None,
            language=payload.language,
            voice=payload.voice,
            from_phone=payload.from_phone,
            sip_user_id=payload.sip_user_id,
            answer_timeout_seconds=payload.answer_timeout_seconds,
            record=payload.record,
            idempotency_key=payload.idempotency_key,
        )
    except IllyVoIPError as exc:
        await _persist_failure(db, tracking, exc)
        logger.warning(
            "vishing_call_failed",
            organization_id=str(organization.id),
            campaign_id=str(campaign.id) if campaign is not None else None,
            employee_id=str(employee.id) if employee is not None else None,
            error_code=exc.error_code,
            provider_status_code=exc.status_code,
        )
        raise _provider_http_error(exc) from exc

    await _persist_success(
        db,
        tracking,
        result,
        employee,
        count_test=tracking_created or tracking is None,
    )
    logger.info(
        "vishing_call_completed",
        organization_id=str(organization.id),
        campaign_id=str(campaign.id) if campaign is not None else None,
        employee_id=str(employee.id) if employee is not None else None,
        call_control_id=result.get("call_control_id"),
        state=result.get("state"),
        call_status=result.get("call_status"),
        duration_seconds=result.get("duration_seconds"),
    )
    return VishingCallResponse(
        call_control_id=str(result.get("call_control_id") or ""),
        employee_id=employee.id if employee is not None else None,
        campaign_id=campaign.id if campaign is not None else None,
        tracking_uuid=tracking.tracking_uuid if tracking is not None else None,
        to_phone_masked=mask_phone(phone),
        state=str(result.get("state") or ""),
        call_status=str(result.get("call_status") or ""),
        answered_at=result.get("answered_at"),
        ended_at=result.get("ended_at"),
        failure_reason=result.get("failure_reason"),
        tts_media=result.get("tts_media"),
        tts_charge=result.get("tts_charge"),
        hangup=result.get("hangup"),
        duration_seconds=float(result.get("duration_seconds") or 0.0),
        rang=bool(result.get("rang")),
        answer_delay_seconds=result.get("answer_delay_seconds"),
        answer_suspect_auto=bool(result.get("answer_suspect_auto")),
    )


@router.get(
    "/calls/{call_control_id}",
    response_model=VishingCallStatusResponse,
    summary="Read one real vishing call status",
)
async def get_vishing_call_status(
    call_control_id: str,
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager", "viewer")),
    db: AsyncSession = Depends(get_db),
) -> VishingCallStatusResponse:
    """Return the provider's current state and refresh the local status."""
    tracking = await _tracking_for_call(db, organization.id, call_control_id)
    service = IllyVoIPService()
    try:
        data = await service.get_call_status(call_control_id)
    except IllyVoIPError as exc:
        raise _provider_http_error(exc) from exc

    terminal = bool(data.get("terminal"))
    answered_at = data.get("answered_at")
    failure_reason = data.get("failure_reason")
    if answered_at and tracking.delivered_at is None:
        tracking.delivered_at = _now()
        tracking.delivery_status = "answered"
        await _record_event(
            db,
            tracking,
            EVENT_VISHING_CALL_ANSWERED,
            details={"call_control_id": call_control_id, "state": data.get("state")},
            provider_message_id=call_control_id,
            delivery_status="answered",
        )
    if terminal:
        if failure_reason:
            tracking.delivery_status = "failed"
            tracking.delivery_error = str(failure_reason)[:500]
            tracking.failed_at = tracking.failed_at or _now()
            await _record_event(
                db,
                tracking,
                EVENT_VISHING_CALL_FAILED,
                details={
                    "call_control_id": call_control_id,
                    "state": data.get("state"),
                    "call_status": data.get("call_status"),
                    "failure_reason": failure_reason,
                },
                provider_message_id=call_control_id,
                delivery_status="failed",
                delivery_error=str(failure_reason),
            )
        elif tracking.completed_at is None:
            tracking.delivery_status = "completed"
            tracking.completed_at = _now()
            await _record_event(
                db,
                tracking,
                EVENT_VISHING_CALL_COMPLETED,
                details={
                    "call_control_id": call_control_id,
                    "state": data.get("state"),
                    "call_status": data.get("call_status"),
                },
                provider_message_id=call_control_id,
                delivery_status="completed",
            )
    await db.commit()
    return VishingCallStatusResponse(
        call_control_id=str(data.get("call_control_id") or call_control_id),
        state=str(data.get("state") or ""),
        call_status=str(data.get("call_status") or ""),
        terminal=terminal,
        answered_at=answered_at,
        ended_at=data.get("ended_at"),
        failure_reason=failure_reason,
    )


@router.post(
    "/calls/{call_control_id}/hangup",
    response_model=VishingHangupResponse,
    summary="Hang up one real vishing call",
)
async def hangup_vishing_call(
    call_control_id: str,
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
    db: AsyncSession = Depends(get_db),
) -> VishingHangupResponse:
    """Explicitly terminate a live call and mark the tracking row completed."""
    tracking = await _tracking_for_call(db, organization.id, call_control_id)
    service = IllyVoIPService()
    try:
        data = await service.hangup(call_control_id)
    except IllyVoIPError as exc:
        raise _provider_http_error(exc) from exc

    tracking.provider = "illyvoip"
    tracking.provider_message_id = call_control_id[:255]
    tracking.delivery_status = "completed"
    tracking.completed_at = tracking.completed_at or _now()
    await _record_event(
        db,
        tracking,
        EVENT_VISHING_CALL_COMPLETED,
        details={
            "call_control_id": call_control_id,
            "message": data.get("message"),
            "idempotent": bool(data.get("idempotent")),
        },
        provider_message_id=call_control_id,
        delivery_status="completed",
    )
    await db.commit()
    return VishingHangupResponse(
        call_control_id=str(data.get("call_control_id") or call_control_id),
        message=str(data.get("message") or ""),
        terminated_channels=int(data.get("terminated_channels") or 0),
        idempotent=bool(data.get("idempotent")),
    )


__all__ = ["router"]
