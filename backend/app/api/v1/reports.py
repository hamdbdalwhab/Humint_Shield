"""Executive PDF report endpoint."""
from __future__ import annotations

import uuid

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import (
    get_current_user,
    get_organization_or_404,
    rate_limit,
    require_permissions,
)
from app.logging_config import get_logger
from app.models import EmailCampaign, HumanAsset, MonthlyArchive, Organization, User
from app.services.employee_service import build_monthly_org_report_pdf, validate_month
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


#: Organization-scoped executive reports.  Kept on its own router so the
#: existing ``/reports`` prefix is untouched.
org_router = APIRouter(
    prefix="/organizations/{org_id}/reports",
    tags=["reports"],
    dependencies=[Depends(rate_limit(limit=20, window=60, scope="org_reports"))],
)


@org_router.get(
    "/monthly",
    summary="Download the monthly organization report (top risk, top reporters)",
    response_class=Response,
)
async def monthly_organization_report(
    org_id: uuid.UUID,
    month: str | None = Query(
        None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM (default: current)"
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("reports.view")),
) -> Response:
    """Render the monthly executive PDF: top 10 risk, top 10 reporters, avg Elo.

    The immutable monthly archive is the source of truth.  When the selected
    month has not been archived yet the live employee scores are used instead,
    so an operator can always obtain the report instead of a 404.
    """
    month_year = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if month is not None:
        validate_month(month_year)

    archived = (
        await db.execute(
            select(MonthlyArchive, HumanAsset)
            .join(HumanAsset, HumanAsset.id == MonthlyArchive.employee_id)
            .where(
                HumanAsset.organization_id == org_id,
                MonthlyArchive.month_year == month_year,
            )
        )
    ).all()

    if archived:
        rows = [
            {
                "employee_name": employee.full_name,
                "email": employee.email,
                "department": employee.department,
                "final_elo_score": int(archive.final_elo_score),
                "total_reports": int(archive.total_reports or 0),
                "total_clicks": int(archive.total_clicks or 0),
                "total_submissions": int(archive.total_submissions or 0),
            }
            for archive, employee in archived
        ]
    else:
        employees = (
            await db.execute(
                select(HumanAsset).where(
                    HumanAsset.organization_id == org_id,
                    HumanAsset.is_active.is_(True),
                )
            )
        ).scalars().all()
        if not employees:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No employees or archives exist for this organization",
            )
        rows = [
            {
                "employee_name": employee.full_name,
                "email": employee.email,
                "department": employee.department,
                "final_elo_score": int(employee.elo_score or 0),
                "total_reports": int(employee.total_reports or 0),
                "total_clicks": int(employee.total_clicks or 0),
                "total_submissions": int(employee.total_credential_submissions or 0),
            }
            for employee in employees
        ]

    pdf = build_monthly_org_report_pdf(organization.name, month_year, rows)
    logger.info(
        "monthly_org_report_generated",
        organization_id=str(org_id),
        month=month_year,
        rows=len(rows),
        user_id=str(user.id),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="monthly-report-{month_year}.pdf"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["org_router", "router"]
