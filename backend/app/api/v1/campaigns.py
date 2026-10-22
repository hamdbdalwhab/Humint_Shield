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
from app.models import EmailCampaign, EmailTemplate, HumanAsset, User
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
)
from app.services.brevo_email_service import BrevoEmailService
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.interaction_report import InteractionReportService
from app.services.live_board import LiveBoardService

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


async def _validate_template(db: AsyncSession, org_id: uuid.UUID, template_id: uuid.UUID) -> EmailTemplate:
    """Assert a template exists, belongs to the org and is active.

    Raises:
        HTTPException: 404 when missing, 400 when inactive.
    """
    template = await db.get(EmailTemplate, template_id)
    if template is None or template.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Template is not active"
        )
    return template


async def _validate_targets(
    db: AsyncSession, org_id: uuid.UUID, employee_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Keep only employee ids that exist within the organization.

    Raises:
        HTTPException: 400 when no valid target remains.
    """
    if not employee_ids:
        return []
    unique_ids = list(dict.fromkeys(employee_ids))
    rows = (
        await db.execute(
            select(HumanAsset.id).where(
                HumanAsset.organization_id == org_id, HumanAsset.id.in_(unique_ids)
            )
        )
    ).scalars().all()
    valid = list(rows)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the selected employees belong to this organization",
        )
    return valid


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
    await _validate_template(db, org_id, payload.template_id)
    valid_targets = await _validate_targets(db, org_id, payload.target_employee_ids)

    campaign = EmailCampaign(
        organization_id=org_id,
        template_id=payload.template_id,
        name=payload.name,
        status="draft",
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
    if data.get("template_id"):
        await _validate_template(db, org_id, data["template_id"])
        campaign.template_id = data["template_id"]
    if "name" in data and data["name"]:
        campaign.name = data["name"]
    # ``difficulty_level`` is accepted for API symmetry but is a property of the
    # template, so it is validated (by the schema) and otherwise not persisted.
    if data.get("target_employee_ids") is not None:
        valid_targets = await _validate_targets(db, org_id, data["target_employee_ids"])
        campaign.target_employee_ids = [str(t) for t in valid_targets]
        campaign.total_targets = len(valid_targets)
    await db.commit()
    await db.refresh(campaign)
    logger.info("campaign_updated", campaign_id=str(campaign_id))
    return CampaignPublic.model_validate(campaign)


@router.delete(
    "/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft campaign"
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

    # Fail fast with an actionable reason when real delivery cannot work.  Without
    # this check the launcher would materialise tracking rows and mark every
    # recipient as failed with no explanation shown in the UI.
    if not get_settings().email_dry_run:
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
    campaign = await _get_campaign(db, org_id, campaign_id)
    employee = await db.get(HumanAsset, employee_id)
    if employee is None or employee.organization_id != org_id:
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
            "department",
            "status",
            "sent_at",
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
                row["department"] or "",
                row["status"],
                row["sent_at"].isoformat() if row["sent_at"] else "",
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
