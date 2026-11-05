"""Email campaign endpoints."""
from __future__ import annotations

import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import (
    SIMULATION_CHANNELS,
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    QRScan,
    User,
)
from app.schemas import (
    CampaignActivity,
    CampaignCreate,
    CampaignPublic,
    CampaignRecipientDetail,
    CampaignResults,
    CampaignUpdate,
    LaunchFailure,
    LaunchResult,
    LiveBoard,
    QRScanAssignRequest,
    QRScanAssignResponse,
    QRScanPublic,
)
from app.services.brevo_email_service import BrevoEmailService
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.interaction_report import InteractionReportService
from app.services.live_board import LiveBoardService
from app.services.tracking_service import TrackingService
from app.services.vonage_service import is_e164_phone

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/email-campaigns",
    tags=["campaigns"],
    dependencies=[Depends(rate_limit(scope="campaigns"))],
)


async def _get_campaign(
    db: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> EmailCampaign:
    """Load a campaign belonging to the organization.

    Raises:
        HTTPException: 404 when not found.
    """
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign


async def _qr_scan_public_rows(
    db: AsyncSession, campaign: EmailCampaign
) -> list[QRScanPublic]:
    """Load the campaign's QR scans and tracking_events and resolve display names."""
    # 1. Load QRScan records
    scans = (
        await db.execute(
            select(QRScan)
            .where(QRScan.campaign_id == campaign.id)
            .order_by(QRScan.occurred_at.desc())
        )
    ).scalars().all()

    # 2. Also fetch all EmailTracking (tracking_events) rows for this campaign where channel == 'qr'
    trackings = (
        await db.execute(
            select(EmailTracking)
            .where(
                EmailTracking.campaign_id == campaign.id,
                EmailTracking.channel == "qr",
            )
            .order_by(EmailTracking.created_at.desc())
        )
    ).scalars().all()

    if not scans and not trackings:
        return []

    tracking_by_id: dict[uuid.UUID, EmailTracking] = {row.id: row for row in trackings}
    for scan in scans:
        if scan.tracking_id and scan.tracking_id not in tracking_by_id:
            t_row = await db.get(EmailTracking, scan.tracking_id)
            if t_row is not None:
                tracking_by_id[t_row.id] = t_row

    employee_ids = {
        emp_id
        for emp_id in [
            *(scan.employee_id for scan in scans),
            *(t.employee_id for t in trackings),
        ]
        if emp_id
    }
    employees: dict[uuid.UUID, HumanAsset] = {}
    if employee_ids:
        rows = (
            await db.execute(
                select(HumanAsset).where(HumanAsset.id.in_(employee_ids))
            )
        ).scalars().all()
        employees = {row.id: row for row in rows}

    result: list[QRScanPublic] = []
    scanned_tracking_ids = set()

    for scan in scans:
        tracking = tracking_by_id.get(scan.tracking_id) if scan.tracking_id else None
        if scan.tracking_id:
            scanned_tracking_ids.add(scan.tracking_id)
        employee = employees.get(scan.employee_id) if scan.employee_id else None
        source = employees.get(tracking.employee_id) if tracking is not None else None
        fingerprint = scan.fingerprint_data if isinstance(scan.fingerprint_data, dict) else {}
        
        events = list(getattr(scan, "real_time_events", None) or [])
        time_on_page = 0
        if len(events) >= 2:
            try:
                from datetime import datetime as _dt
                t0 = _dt.fromisoformat(events[0]["timestamp"])
                t_last = _dt.fromisoformat(events[-1]["timestamp"])
                time_on_page = max(0, int((t_last - t0).total_seconds()))
            except Exception:
                pass

        city = getattr(scan, "city", None)
        country = getattr(scan, "country", None)
        isp = getattr(scan, "isp", None)
        loc_parts = [p for p in (city, country) if p]
        location_display = ", ".join(loc_parts) if loc_parts else None
        if location_display and isp:
            location_display += f" (ISP: {isp})"

        result.append(
            QRScanPublic(
                id=scan.id,
                campaign_id=scan.campaign_id,
                tracking_id=scan.tracking_id,
                tracking_uuid=tracking.tracking_uuid if tracking is not None else None,
                source_employee_id=source.id if source is not None else None,
                source_employee_name=source.full_name if source is not None else None,
                source_employee_email=source.email if source is not None else None,
                employee_id=scan.employee_id,
                employee_name=employee.full_name if employee is not None else None,
                employee_email=employee.email if employee is not None else None,
                username=scan.username,
                email=scan.email,
                password_submitted=bool(scan.password_submitted),
                identity_resolution=scan.identity_resolution or "unknown",
                event_type=getattr(scan, "event_type", "qr_scanned") or "qr_scanned",
                occurred_at=scan.occurred_at,
                ip_address=scan.ip_address,
                user_agent=scan.user_agent,
                fingerprint=fingerprint,
                device_info=fingerprint,
                fingerprint_hash=fingerprint.get("fingerprint_hash"),
                username_entered=scan.username,
                email_entered=scan.email,
                device_model=getattr(scan, "device_model", None),
                country=country,
                city=city,
                isp=isp,
                location_display=location_display,
                latitude=getattr(scan, "latitude", None),
                longitude=getattr(scan, "longitude", None),
                real_time_events=events,
                time_on_page_seconds=time_on_page,
                elo_delta=scan.elo_delta or 0,
                penalty_applied=bool(scan.penalty_applied),
            )
        )

    # Add any tracking_events that do not have a corresponding QRScan row yet
    for tracking in trackings:
        if tracking.id in scanned_tracking_ids:
            continue
        employee = employees.get(tracking.employee_id) if tracking.employee_id else None
        client_ctx = tracking.client_context if isinstance(tracking.client_context, dict) else {}
        fp = client_ctx.get("fingerprint") or client_ctx or {}
        loc = ", ".join([p for p in (client_ctx.get("city"), client_ctx.get("country")) if p]) or None
        result.append(
            QRScanPublic(
                id=tracking.id,
                campaign_id=campaign.id,
                tracking_id=tracking.id,
                tracking_uuid=tracking.tracking_uuid,
                source_employee_id=employee.id if employee else None,
                source_employee_name=employee.full_name if employee else None,
                source_employee_email=employee.email if employee else None,
                employee_id=employee.id if employee else None,
                employee_name=employee.full_name if employee else None,
                employee_email=employee.email if employee else None,
                username=tracking.submitted_username,
                email=tracking.submitted_email,
                password_submitted=bool(tracking.password_submitted),
                identity_resolution=tracking.identity_resolution or "unknown",
                event_type=tracking.event_type or "qr_scanned",
                occurred_at=tracking.created_at or tracking.opened_at,
                ip_address=tracking.last_ip_address,
                user_agent=tracking.last_user_agent,
                fingerprint=fp,
                device_info=fp,
                fingerprint_hash=fp.get("fingerprint_hash"),
                username_entered=tracking.submitted_username,
                email_entered=tracking.submitted_email,
                device_model=client_ctx.get("device_model"),
                country=client_ctx.get("country"),
                city=client_ctx.get("city"),
                isp=client_ctx.get("isp"),
                location_display=loc,
                latitude=client_ctx.get("latitude"),
                longitude=client_ctx.get("longitude"),
                real_time_events=[],
                time_on_page_seconds=0,
                elo_delta=-25 if tracking.qr_penalty_applied else 0,
                penalty_applied=bool(tracking.qr_penalty_applied),
            )
        )

    result.sort(key=lambda s: s.occurred_at, reverse=True)
    return result


@router.get(
    "/{campaign_id}/scans",
    response_model=list[QRScanPublic],
    summary="QR campaign live scans (the Radar)",
)
async def campaign_qr_scans(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[QRScanPublic]:
    """Return every QR form submission, including unknown identities."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    return await _qr_scan_public_rows(db, campaign)


@router.post(
    "/{campaign_id}/scans/{scan_id}/assign",
    response_model=QRScanAssignResponse,
    summary="Assign an unknown QR scan to an employee",
)
async def assign_campaign_qr_scan(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    scan_id: uuid.UUID,
    payload: QRScanAssignRequest,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> QRScanAssignResponse:
    """Manually link an Unknown scan and apply the once-only -25 Elo penalty."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    scan = await db.get(QRScan, scan_id)
    if scan is None or scan.campaign_id != campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    employee = await db.get(HumanAsset, payload.employee_id)
    if employee is None or employee.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    try:
        result = await TrackingService().assign_qr_scan(
            scan.id,
            employee.id,
            db,
            actor=user.username or "administrator",
            ip_address=None,
            user_agent=None,
        )
        if result is None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found"
            )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    refreshed = await _qr_scan_public_rows(db, campaign)
    scan_public = next((row for row in refreshed if row.id == scan_id), None)
    return QRScanAssignResponse(
        success=True,
        message="تم ربط المسح بالموظف وتطبيق خصم Elo عند الحاجة.",
        scan=scan_public,
        elo_score=int(employee.elo_score) if employee.elo_score is not None else None,
        elo_delta=scan_public.elo_delta if scan_public is not None else 0,
    )


async def _validate_template(
    db: AsyncSession,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    channel: str = "email",
) -> EmailTemplate:
    """Assert a template exists, belongs to the org, is active and matches the channel.

    Raises:
        HTTPException: 404 when missing, 400 when inactive or channel-mismatched.
    """
    template = await db.get(EmailTemplate, template_id)
    if template is None or template.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Template is not active"
        )
    if channel == "qr":
        # QR campaigns use a dedicated, printable lure template.  They must
        # never silently reuse an email template.
        template_channel = template.channel or "email"
        if template_channel != "qr":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "QR campaigns require a QR template; "
                    f"template channel is '{template_channel}'"
                ),
            )
        return template
    if channel in SIMULATION_CHANNELS:
        # Vishing/pretexting/USB reuse an active email template as their
        # scenario reference; they do not deliver through the email provider.
        return template
    if (template.channel or "email") != channel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Template channel '{template.channel}' does not match "
                f"campaign channel '{channel}'"
            ),
        )
    return template


async def _validate_targets(
    db: AsyncSession,
    org_id: uuid.UUID,
    employee_ids: list[uuid.UUID],
    channel: str = "email",
) -> list[uuid.UUID]:
    """Keep employee ids that exist in the organization and can receive the channel.

    For SMS/WhatsApp every target must have a valid E.164 phone number.  This
    prevents a recipient without a number from being selected, and also blocks a
    silent skip at send time.

    Raises:
        HTTPException: 400 when no valid target remains or a phone channel has
            recipients without a usable E.164 number.
    """
    if not employee_ids:
        return []
    unique_ids = list(dict.fromkeys(employee_ids))
    rows = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == org_id, HumanAsset.id.in_(unique_ids)
            )
        )
    ).scalars().all()
    valid = [employee for employee in rows]
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the selected employees belong to this organization",
        )
    if (channel or "email").lower() in {"sms", "whatsapp"}:
        missing = [employee.email for employee in valid if not (employee.phone or "").strip()]
        invalid = [
            f"{employee.email} ({employee.phone})"
            for employee in valid
            if (employee.phone or "").strip() and not is_e164_phone(employee.phone)
        ]
        if missing or invalid:
            problems: list[str] = []
            if missing:
                problems.append(f"missing phone number: {', '.join(missing[:10])}")
            if invalid:
                problems.append(f"phone not in E.164 format: {', '.join(invalid[:10])}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{channel.upper()} campaigns require a valid E.164 phone number "
                    f"for every target. {'; '.join(problems)}"
                ),
            )
    return [employee.id for employee in valid]


@router.get("", response_model=list[CampaignPublic], summary="List campaigns")
async def list_campaigns(
    org_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status", pattern="^(draft|active|completed|aborted)$"),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[CampaignPublic]:
    """List the organization's campaigns, newest first."""
    filters = [EmailCampaign.organization_id == org_id]
    if status_filter:
        filters.append(EmailCampaign.status == status_filter)
    rows = (
        await db.execute(
            select(EmailCampaign).where(*filters).order_by(EmailCampaign.created_at.desc())
        )
    ).scalars().all()
    return [CampaignPublic.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=CampaignPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign (draft)",
)
async def create_campaign(
    org_id: uuid.UUID,
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> CampaignPublic:
    """Create a campaign in ``draft`` status.

    Raises:
        HTTPException: 404 when the template is unknown, 400 when no valid
            target is provided.
    """
    await _validate_template(db, org_id, payload.template_id, payload.channel)
    valid_targets = await _validate_targets(
        db, org_id, payload.target_employee_ids, payload.channel
    )

    campaign = EmailCampaign(
        organization_id=org_id,
        template_id=payload.template_id,
        name=payload.name,
        channel=payload.channel,
        channel_config=payload.channel_config or {},
        status="draft",
        auto_retest_failed=payload.auto_retest_failed,
        target_employee_ids=[str(t) for t in valid_targets],
        total_targets=len(valid_targets),
        created_by=user.id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    logger.info(
        "campaign_created",
        campaign_id=str(campaign.id),
        targets=len(valid_targets),
        org_id=str(org_id),
    )
    return CampaignPublic.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignPublic, summary="Get a campaign")
async def get_campaign(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> CampaignPublic:
    """Return a single campaign."""
    return CampaignPublic.model_validate(await _get_campaign(db, org_id, campaign_id))


@router.put("/{campaign_id}", response_model=CampaignPublic, summary="Update a draft campaign")
async def update_campaign(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> CampaignPublic:
    """Update a campaign; only permitted while it is a ``draft``.

    Raises:
        HTTPException: 400 when the campaign is no longer a draft.
    """
    campaign = await _get_campaign(db, org_id, campaign_id)
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign is '{campaign.status}' and can no longer be edited",
        )
    data = payload.model_dump(exclude_unset=True)
    channel = data.get("channel", campaign.channel or "email")
    if data.get("template_id"):
        await _validate_template(db, org_id, data["template_id"], channel)
        campaign.template_id = data["template_id"]
    elif "channel" in data and campaign.template_id is not None:
        # The UI clears the template when the channel changes, but an API client
        # may switch channels alone. Fail now rather than at launch.
        await _validate_template(db, org_id, campaign.template_id, channel)
    if "channel" in data and data["channel"]:
        campaign.channel = data["channel"]
    if "name" in data and data["name"]:
        campaign.name = data["name"]
    if "channel_config" in data:
        campaign.channel_config = data["channel_config"] or {}
    if "auto_retest_failed" in data and data["auto_retest_failed"] is not None:
        campaign.auto_retest_failed = bool(data["auto_retest_failed"])
    # ``difficulty_level`` is accepted for API symmetry but is a property of the
    # template, so it is validated (by the schema) and otherwise not persisted.
    if data.get("target_employee_ids") is not None:
        valid_targets = await _validate_targets(
            db, org_id, data["target_employee_ids"], channel
        )
        campaign.target_employee_ids = [str(t) for t in valid_targets]
        campaign.total_targets = len(valid_targets)
    elif "channel" in data and (channel or "email").lower() in {"sms", "whatsapp"}:
        # Changing an existing draft to a phone channel must validate the
        # already-selected recipients too, not just newly supplied ones.
        existing_ids: list[uuid.UUID] = []
        for value in campaign.target_employee_ids or []:
            try:
                existing_ids.append(uuid.UUID(str(value)))
            except (ValueError, AttributeError, TypeError):
                continue
        await _validate_targets(db, org_id, existing_ids, channel)
    await db.commit()
    await db.refresh(campaign)
    logger.info("campaign_updated", campaign_id=str(campaign_id))
    return CampaignPublic.model_validate(campaign)


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft campaign",
    response_model=None,
)
async def delete_campaign(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin")),
) -> None:
    """Delete a campaign; only permitted while it is a ``draft``."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign is '{campaign.status}' and cannot be deleted",
        )
    await db.delete(campaign)
    await db.commit()
    logger.info("campaign_deleted", campaign_id=str(campaign_id))


@router.post(
    "/{campaign_id}/launch",
    response_model=LaunchResult,
    summary="Launch a campaign (sends real emails)",
)
async def launch_campaign(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    background_tasks: bool = Query(
        False,
        alias="background",
        description="Dispatch to the Celery queue instead of sending inline",
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> LaunchResult:
    """Send the campaign to all targets.

    By default the send happens inline so the caller receives the complete
    result.  With ``?background=true`` the work is handed to Celery (used for
    very large campaigns); if the broker is unavailable the request silently
    falls back to the inline path so no simulation is ever lost.

    Raises:
        HTTPException: 400 when the campaign cannot be launched.
    """
    campaign = await _get_campaign(db, org_id, campaign_id)
    channel = (campaign.channel or "email").strip().lower()

    # Re-validate the target phones at launch time: an employee's number may
    # have been removed after the draft was created.
    if channel in {"sms", "whatsapp"}:
        launch_targets: list[uuid.UUID] = []
        for value in campaign.target_employee_ids or []:
            try:
                launch_targets.append(uuid.UUID(str(value)))
            except (ValueError, AttributeError, TypeError):
                continue
        await _validate_targets(db, org_id, launch_targets, channel)

    settings = get_settings()
    if channel == "email":
        # Fail fast with an actionable reason when real email delivery cannot
        # work.  Without this check the launcher would materialise tracking rows
        # and mark every recipient as failed with no explanation shown in the UI.
        if not settings.email_dry_run:
            brevo_check = await BrevoEmailService().verify_configuration()
            if not brevo_check.get("valid"):
                hint = (
                    brevo_check.get("hint")
                    or brevo_check.get("error")
                    or "Brevo rejected the request"
                )
                logger.warning(
                    "campaign_launch_blocked_brevo",
                    campaign_id=str(campaign_id),
                    error=hint,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Real delivery is blocked: {hint}",
                )
    elif channel in {"sms", "whatsapp"}:
        ready = (
            settings.vonage_sms_configured
            if channel == "sms"
            else settings.vonage_whatsapp_configured
        )
        if not ready:
            missing = settings.vonage_missing_settings(channel)
            hint = ", ".join(missing) if missing else "Vonage credentials/sender are incomplete"
            logger.warning(
                "campaign_launch_blocked_vonage",
                campaign_id=str(campaign_id),
                channel=channel,
                missing=missing,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Real {channel.upper()} delivery is blocked: configure {hint} "
                    "in backend/.env and restart the server."
                ),
            )

    if background_tasks:
        dispatched = _dispatch_to_celery(str(campaign.id))
        if dispatched:
            logger.info("campaign_launch_queued", campaign_id=str(campaign_id))
            return LaunchResult(
                campaign_id=campaign.id,
                total=campaign.total_targets or 0,
                sent=0,
                failed=0,
                failures=[],
            )

    launcher = CampaignLauncher()
    try:
        result = await launcher.launch_campaign(campaign.id, db)
    except CampaignLaunchError as exc:
        logger.warning("campaign_launch_rejected", campaign_id=str(campaign_id), error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return LaunchResult(
        campaign_id=result["campaign_id"],
        total=result["total"],
        sent=result["sent"],
        failed=result["failed"],
        failures=[LaunchFailure(**f) for f in result["failures"]],
    )


def _dispatch_to_celery(campaign_id: str) -> bool:
    """Enqueue a campaign launch on the Celery broker.

    Args:
        campaign_id: The campaign to enqueue.

    Returns:
        ``True`` when the task was accepted by the broker.
    """
    try:
        from app.worker.tasks import launch_campaign as launch_task

        launch_task.delay(campaign_id)
        return True
    except Exception as exc:  # noqa: BLE001 - broker may be unavailable
        logger.warning("celery_dispatch_failed", campaign_id=campaign_id, error=str(exc))
        return False


@router.get(
    "/{campaign_id}/results", response_model=CampaignResults, summary="Campaign engagement results"
)
async def campaign_results(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> CampaignResults:
    """Return per-employee engagement plus aggregate stats."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    launcher = CampaignLauncher()
    try:
        data = await launcher.get_campaign_results(campaign.id, db)
    except CampaignLaunchError as exc:  # pragma: no cover - campaign already checked
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CampaignResults(
        campaign=CampaignPublic.model_validate(data["campaign"]),
        stats=data["stats"],
        employees=data["employees"],
        scans=await _qr_scan_public_rows(db, campaign),
    )


@router.get(
    "/{campaign_id}/live",
    response_model=LiveBoard,
    summary="Live monitoring board (poll every 1-2 seconds)",
)
async def campaign_live_board(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> LiveBoard:
    """Return the real-time state of every recipient in the campaign.

    The payload is intentionally compact and safe to poll while a simulation is
    running: one entry per recipient with the derived funnel status, every
    transition timestamp, the seconds between them, the last observed event with
    IP/device, and the campaign-wide activity ticker.

    Raises:
        HTTPException: 404 when the campaign is unknown.
    """
    campaign = await _get_campaign(db, org_id, campaign_id)
    data = await LiveBoardService().build(campaign, db)
    return LiveBoard.model_validate(data)


@router.get(
    "/{campaign_id}/recipients/{employee_id}",
    response_model=CampaignRecipientDetail,
    summary="One recipient's complete record inside a campaign",
)
async def campaign_recipient(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> CampaignRecipientDetail:
    """Return the second-by-second record of one recipient.

    Includes the full interaction ledger (every open, click, form render,
    submission, report and completion with exact timestamps, IP and device) and
    every value the recipient typed, decrypted from storage.

    Raises:
        HTTPException: 404 when the campaign or the recipient is unknown.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    campaign = await _get_campaign(db, org_id, campaign_id)
    employee = await db.get(HumanAsset, employee_id)
    if employee is None:
        tracking = await db.get(EmailTracking, employee_id)
        if tracking is None:
            tracking = await db.scalar(
                select(EmailTracking).where(
                    EmailTracking.campaign_id == campaign.id,
                    EmailTracking.tracking_uuid == employee_id,
                )
            )
        if tracking is not None and tracking.campaign_id == campaign.id:
            if tracking.employee_id:
                employee = await db.get(HumanAsset, tracking.employee_id)
            if employee is None:
                now_ts = datetime.now(timezone.utc)
                employee = HumanAsset(
                    id=tracking.id,
                    organization_id=org_id,
                    email=tracking.submitted_email or "unknown@qr.visitor",
                    first_name=tracking.submitted_username or "زائر QR",
                    last_name="(غير مسجل)",
                    department="QR Capture",
                    job_title="Mobile / External",
                    access_level=1,
                    immunity_score=Decimal("0.0"),
                    elo_score=1000,
                    behavioral_category="unaware",
                    total_tests_received=1,
                    total_clicks=1,
                    total_reports=0,
                    total_credential_submissions=1 if tracking.submitted_at else 0,
                    total_ignores=0,
                    is_active=True,
                    is_on_leave=False,
                    requires_mandatory_training=False,
                    under_enhanced_monitoring=False,
                    created_at=tracking.created_at or now_ts,
                    updated_at=tracking.submitted_at or now_ts,
                )
    if employee is None or (hasattr(employee, "organization_id") and employee.organization_id != org_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    service = InteractionReportService()
    try:
        data = await service.campaign_recipient(campaign, employee, db)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CampaignRecipientDetail.model_validate(data)


@router.get(
    "/{campaign_id}/activity",
    response_model=CampaignActivity,
    summary="The campaign's complete interaction ledger",
)
async def campaign_activity(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> CampaignActivity:
    """Return every recorded interaction in the campaign, oldest first."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    launcher = CampaignLauncher()
    data = await launcher.get_campaign_results(campaign.id, db)
    events = await InteractionReportService().campaign_activity(campaign, db, limit=limit)
    return CampaignActivity(
        campaign=CampaignPublic.model_validate(data["campaign"]),
        stats=data["stats"],
        events=events,
    )


@router.get("/{campaign_id}/export", summary="Export campaign results as CSV")
async def export_campaign(
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> Response:
    """Download the campaign's per-employee results as CSV."""
    campaign = await _get_campaign(db, org_id, campaign_id)
    launcher = CampaignLauncher()
    data = await launcher.get_campaign_results(campaign.id, db)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "employee_id",
            "name",
            "email",
            "phone",
            "channel",
            "department",
            "status",
            "sent_at",
            "delivered_at",
            "delivery_status",
            "delivery_error",
            "read_at",
            "failed_at",
            "provider_message_id",
            "opened_at",
            "clicked_at",
            "form_viewed_at",
            "submitted_at",
            "completed_at",
            "reported_at",
            "open_count",
            "click_count",
            "submission_count",
            "submitted_identifier",
            "submitted_values_json",
            "password_length",
            "immunity_score",
            "behavioral_category",
        ]
    )
    for row in data["employees"]:
        writer.writerow(
            [
                row["employee_id"],
                row["name"],
                row["email"],
                row.get("phone") or "",
                row.get("channel") or "",
                row["department"] or "",
                row["status"],
                row["sent_at"].isoformat() if row["sent_at"] else "",
                row["delivered_at"].isoformat() if row.get("delivered_at") else "",
                row.get("delivery_status") or "",
                row.get("delivery_error") or "",
                row["read_at"].isoformat() if row.get("read_at") else "",
                row["failed_at"].isoformat() if row.get("failed_at") else "",
                row.get("provider_message_id") or "",
                row["opened_at"].isoformat() if row["opened_at"] else "",
                row["clicked_at"].isoformat() if row["clicked_at"] else "",
                row["form_viewed_at"].isoformat() if row["form_viewed_at"] else "",
                row["submitted_at"].isoformat() if row["submitted_at"] else "",
                row["completed_at"].isoformat() if row["completed_at"] else "",
                row["reported_at"].isoformat() if row["reported_at"] else "",
                row["open_count"],
                row["click_count"],
                row["submission_count"],
                row["submitted_identifier"] or "",
                json.dumps(row["submitted_values"], ensure_ascii=False)
                if row.get("submitted_values")
                else "",
                row["password_length"] if row["password_length"] is not None else "",
                row["immunity_score"] if row["immunity_score"] is not None else "",
                row["behavioral_category"] or "",
            ]
        )
    filename = f"campaign_{campaign.id}.csv"
    return Response(
        # A UTF-8 BOM keeps Arabic names readable when opened in Excel.
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
