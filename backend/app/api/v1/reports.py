"""Executive PDF report endpoint."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, rate_limit, require_permissions
from app.logging_config import get_logger
from app.models import EmailCampaign, Organization, User
from app.services.executive_report import ExecutiveReportService

logger = get_logger(__name__)

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(rate_limit(limit=20, window=60, scope="executive_reports"))],
)


@router.get(
    "/executive-pdf",
    summary="Download the executive PDF report for a campaign",
    response_class=Response,
)
async def executive_pdf(
    campaign_id: uuid.UUID = Query(..., description="Campaign to report on"),
    user: User = Depends(require_permissions("reports.view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate a PDF scoped to the authenticated user's organization.

    A campaign from another tenant is deliberately indistinguishable from a
    missing campaign (``404``), so the endpoint cannot be used to enumerate
    other organizations' campaign IDs.
    """
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The authenticated user is not attached to an organization",
        )
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )

    try:
        pdf_bytes = await ExecutiveReportService().generate(campaign, organization, db)
    except Exception as exc:  # noqa: BLE001 - return a clean error, log the cause
        logger.exception(
            "executive_report_failed",
            campaign_id=str(campaign.id),
            organization_id=str(organization.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate the executive report",
        ) from exc

    filename = f"executive-report-{campaign.id}.pdf"
    logger.info(
        "executive_report_generated",
        campaign_id=str(campaign.id),
        organization_id=str(organization.id),
        user_id=str(user.id),
        bytes=len(pdf_bytes),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
