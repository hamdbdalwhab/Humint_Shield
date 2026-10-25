"""Existing LMS endpoints: dashboard, training library, assignments, report inbox.

These back the pre-existing pages (Training Library, Assignments, My Training,
Report Inbox).  The campaign subsystem is additive and never mutates them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    PhishingReport,
    TrainingAssignment,
    TrainingInteraction,
    TrainingModule,
    User,
)
from app.services.interaction_report import EVENT_LABELS
from app.schemas import (
    AssignmentCreate,
    AssignmentPublic,
    DashboardSummary,
    PhishingReportCreate,
    PhishingReportPublic,
    PhishingReportUpdate,
    TrainingModuleCreate,
    TrainingModulePublic,
)

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}",
    tags=["lms"],
    dependencies=[Depends(rate_limit(scope="lms"))],
)


def _now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/dashboard", response_model=DashboardSummary, summary="Dashboard summary")
async def dashboard(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> DashboardSummary:
    """Aggregate headline metrics for the dashboard page."""
    total_employees = await db.scalar(
        select(func.count(HumanAsset.id)).where(HumanAsset.organization_id == org_id)
    ) or 0
    active_employees = await db.scalar(
        select(func.count(HumanAsset.id)).where(
            HumanAsset.organization_id == org_id, HumanAsset.is_active.is_(True)
        )
    ) or 0
    critical = await db.scalar(
        select(func.count(HumanAsset.id)).where(
            HumanAsset.organization_id == org_id,
            HumanAsset.behavioral_category == "critical_risk",
        )
    ) or 0
    total_campaigns = await db.scalar(
        select(func.count(EmailCampaign.id)).where(EmailCampaign.organization_id == org_id)
    ) or 0
    active_campaigns = await db.scalar(
        select(func.count(EmailCampaign.id)).where(
            EmailCampaign.organization_id == org_id, EmailCampaign.status == "active"
        )
    ) or 0
    total_templates = await db.scalar(
        select(func.count(EmailTemplate.id)).where(EmailTemplate.organization_id == org_id)
    ) or 0

    aggregates = (
        await db.execute(
            select(
                func.coalesce(func.sum(EmailCampaign.sent_count), 0),
                func.coalesce(func.sum(EmailCampaign.opened_count), 0),
                func.coalesce(func.sum(EmailCampaign.clicked_count), 0),
                func.coalesce(func.sum(EmailCampaign.completed_count), 0),
            ).where(EmailCampaign.organization_id == org_id)
        )
    ).one()
    sent, opened, clicked, completed = (int(v or 0) for v in aggregates)

    total_submitted = await db.scalar(
        select(func.count(EmailTracking.id))
        .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
        .where(
            EmailCampaign.organization_id == org_id,
            EmailTracking.submitted_at.is_not(None),
        )
    ) or 0

    reports_pending = await db.scalar(
        select(func.count(PhishingReport.id)).where(
            PhishingReport.organization_id == org_id, PhishingReport.status == "new"
        )
    ) or 0

    recent_rows = (
        await db.execute(
            select(EmailCampaign)
            .where(EmailCampaign.organization_id == org_id)
            .order_by(EmailCampaign.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_campaigns = [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "sent": c.sent_count,
            "opened": c.opened_count,
            "clicked": c.clicked_count,
            "completed": c.completed_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in recent_rows
    ]

    # --- live activity feed (real ledger rows, newest first) --------------- #
    event_rows = (
        await db.execute(
            select(TrainingInteraction, HumanAsset, EmailCampaign)
            .join(HumanAsset, HumanAsset.id == TrainingInteraction.employee_id)
            .join(EmailCampaign, EmailCampaign.id == TrainingInteraction.campaign_id)
            .where(EmailCampaign.organization_id == org_id)
            .order_by(TrainingInteraction.occurred_at.desc())
            .limit(14)
        )
    ).all()
    recent_events = [
        {
            "id": str(interaction.id),
            "employee_id": str(employee.id),
            "employee_name": (
                f"{employee.first_name or ''} {employee.last_name or ''}".strip()
                or employee.email
            ),
            "employee_email": employee.email,
            "event_type": interaction.event_type,
            "label": EVENT_LABELS.get(
                interaction.event_type,
                interaction.event_type.replace("_", " ").title(),
            ),
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "occurred_at": interaction.occurred_at.isoformat()
            if interaction.occurred_at
            else None,
            "ip_address": str(interaction.ip_address) if interaction.ip_address else None,
        }
        for interaction, employee, campaign in event_rows
    ]

    # --- seven-day engagement trend (computed from ledger timestamps) ------ #
    today = _now().date()
    start_day = today - timedelta(days=6)
    buckets = {
        (start_day + timedelta(days=offset)).isoformat(): {
            "date": (start_day + timedelta(days=offset)).isoformat(),
            "opens": 0,
            "clicks": 0,
            "submissions": 0,
            "completed": 0,
        }
        for offset in range(7)
    }
    trend_rows = (
        await db.execute(
            select(TrainingInteraction.event_type, TrainingInteraction.occurred_at)
            .join(EmailCampaign, EmailCampaign.id == TrainingInteraction.campaign_id)
            .where(
                EmailCampaign.organization_id == org_id,
                TrainingInteraction.occurred_at >= datetime.combine(
                    start_day, datetime.min.time(), tzinfo=timezone.utc
                ),
            )
        )
    ).all()
    trend_map = {
        "email_open": "opens",
        "email_opened": "opens",
        "link_click": "clicks",
        "link_clicked": "clicks",
        "form_submitted": "submissions",
        "credentials_submitted": "submissions",
        "training_completed": "completed",
    }
    for event_type, occurred_at in trend_rows:
        if occurred_at is None:
            continue
        key = occurred_at.date().isoformat()
        bucket = buckets.get(key)
        field = trend_map.get(event_type)
        if bucket is not None and field is not None:
            bucket[field] += 1
    engagement_trend = list(buckets.values())

    return DashboardSummary(
        total_employees=total_employees,
        active_employees=active_employees,
        total_campaigns=total_campaigns,
        active_campaigns=active_campaigns,
        total_templates=total_templates,
        total_emails_sent=sent,
        total_opened=opened,
        total_clicked=clicked,
        total_submitted=int(total_submitted),
        total_completed=completed,
        open_rate=round(opened / sent * 100, 2) if sent else 0.0,
        click_rate=round(clicked / sent * 100, 2) if sent else 0.0,
        submission_rate=round(int(total_submitted) / sent * 100, 2) if sent else 0.0,
        reports_pending=reports_pending,
        critical_risk_employees=critical,
        recent_campaigns=recent_campaigns,
        recent_events=recent_events,
        engagement_trend=engagement_trend,
    )


# --------------------------------------------------------------------------- #
# Training library
# --------------------------------------------------------------------------- #
@router.get(
    "/training-modules",
    response_model=list[TrainingModulePublic],
    summary="List training-library modules",
)
async def list_modules(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[TrainingModulePublic]:
    """Return the training-library catalogue."""
    rows = (
        await db.execute(
            select(TrainingModule)
            .where(TrainingModule.organization_id == org_id)
            .order_by(TrainingModule.created_at.asc())
        )
    ).scalars().all()
    return [TrainingModulePublic.model_validate(row) for row in rows]


@router.post(
    "/training-modules",
    response_model=TrainingModulePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a training module",
)
async def create_module(
    org_id: uuid.UUID,
    payload: TrainingModuleCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> TrainingModulePublic:
    """Add a module to the training library."""
    module = TrainingModule(organization_id=org_id, **payload.model_dump())
    db.add(module)
    await db.commit()
    await db.refresh(module)
    return TrainingModulePublic.model_validate(module)


# --------------------------------------------------------------------------- #
# Assignments
# --------------------------------------------------------------------------- #
def _assignment_public(assignment: TrainingAssignment) -> AssignmentPublic:
    """Serialise an assignment, flattening module/employee display fields."""
    employee = assignment.employee
    module = assignment.module
    payload = AssignmentPublic.model_validate(assignment)
    payload.module_title = module.title if module else None
    if employee is not None:
        payload.employee_name = employee.full_name
        payload.employee_email = employee.email
    return payload


async def _load_assignment(
    db: AsyncSession, org_id: uuid.UUID, assignment_id: uuid.UUID
) -> TrainingAssignment:
    """Load an assignment with its module and employee eagerly.

    Raises:
        HTTPException: 404 when not found in the organization.
    """
    row = (
        await db.execute(
            select(TrainingAssignment)
            .options(
                selectinload(TrainingAssignment.module),
                selectinload(TrainingAssignment.employee),
            )
            .where(
                TrainingAssignment.id == assignment_id,
                TrainingAssignment.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    return row


@router.get("/assignments", response_model=list[AssignmentPublic], summary="List assignments")
async def list_assignments(
    org_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status", max_length=20),
    employee_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[AssignmentPublic]:
    """List assignments, optionally filtered by status/employee."""
    filters = [TrainingAssignment.organization_id == org_id]
    if status_filter:
        filters.append(TrainingAssignment.status == status_filter)
    if employee_id:
        filters.append(TrainingAssignment.employee_id == employee_id)
    rows = (
        await db.execute(
            select(TrainingAssignment)
            .options(
                selectinload(TrainingAssignment.module),
                selectinload(TrainingAssignment.employee),
            )
            .where(*filters)
            .order_by(TrainingAssignment.created_at.desc())
        )
    ).scalars().all()
    return [_assignment_public(row) for row in rows]


@router.post(
    "/assignments",
    response_model=AssignmentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a module to an employee",
)
async def create_assignment(
    org_id: uuid.UUID,
    payload: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> AssignmentPublic:
    """Create an assignment.

    Raises:
        HTTPException: 404 when the module or employee is unknown.
    """
    module = await db.get(TrainingModule, payload.module_id)
    if module is None or module.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    if payload.employee_id is not None:
        employee = await db.get(HumanAsset, payload.employee_id)
        if employee is None or employee.organization_id != org_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    assignment = TrainingAssignment(
        organization_id=org_id,
        module_id=payload.module_id,
        employee_id=payload.employee_id,
        due_date=payload.due_date,
        notes=payload.notes,
        status="assigned",
    )
    db.add(assignment)
    await db.commit()
    loaded = await _load_assignment(db, org_id, assignment.id)
    logger.info("assignment_created", assignment_id=str(assignment.id))
    return _assignment_public(loaded)


@router.post(
    "/assignments/{assignment_id}/complete",
    response_model=AssignmentPublic,
    summary="Mark an assignment complete",
)
async def complete_assignment(
    org_id: uuid.UUID,
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> AssignmentPublic:
    """Mark an assignment as completed.

    Raises:
        HTTPException: 404 when the assignment is unknown.
    """
    assignment = await db.get(TrainingAssignment, assignment_id)
    if assignment is None or assignment.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    assignment.status = "completed"
    assignment.completed_at = _now()
    await db.commit()
    loaded = await _load_assignment(db, org_id, assignment_id)
    return _assignment_public(loaded)


# --------------------------------------------------------------------------- #
# Report inbox
# --------------------------------------------------------------------------- #
@router.get("/reports", response_model=list[PhishingReportPublic], summary="List reported emails")
async def list_reports(
    org_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status", max_length=20),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[PhishingReportPublic]:
    """List the report inbox, newest first."""
    filters = [PhishingReport.organization_id == org_id]
    if status_filter:
        filters.append(PhishingReport.status == status_filter)
    rows = (
        await db.execute(
            select(PhishingReport)
            .where(*filters)
            .order_by(PhishingReport.created_at.desc())
        )
    ).scalars().all()
    return [PhishingReportPublic.model_validate(row) for row in rows]


@router.post(
    "/reports",
    response_model=PhishingReportPublic,
    status_code=status.HTTP_201_CREATED,
    summary="File a suspicious-email report",
)
async def create_report(
    org_id: uuid.UUID,
    payload: PhishingReportCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> PhishingReportPublic:
    """File a report (a positive security behaviour).

    When the report is attributed to an employee their ``total_reports``
    counter is incremented, which feeds the classification engine.
    """
    report = PhishingReport(
        organization_id=org_id,
        employee_id=payload.employee_id,
        reported_email_subject=payload.reported_email_subject,
        reported_sender=payload.reported_sender,
        description=payload.description,
        is_training_simulation=payload.is_training_simulation,
        status="new",
    )
    db.add(report)
    if payload.employee_id is not None:
        employee = await db.get(HumanAsset, payload.employee_id)
        if employee is not None and employee.organization_id == org_id:
            employee.total_reports = (employee.total_reports or 0) + 1
        else:
            report.employee_id = None
    await db.commit()
    await db.refresh(report)
    return PhishingReportPublic.model_validate(report)


@router.put(
    "/reports/{report_id}", response_model=PhishingReportPublic, summary="Triage a report"
)
async def update_report(
    org_id: uuid.UUID,
    report_id: uuid.UUID,
    payload: PhishingReportUpdate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> PhishingReportPublic:
    """Update a report's triage status and notes.

    Raises:
        HTTPException: 404 when the report is unknown.
    """
    report = await db.get(PhishingReport, report_id)
    if report is None or report.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(report, field, value)
    await db.commit()
    await db.refresh(report)
    return PhishingReportPublic.model_validate(report)
