"""Employee (human asset) endpoints."""
from __future__ import annotations

import csv
import io
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, User
from app.schemas import (
    BulkImportResult,
    EmployeeCreate,
    EmployeeDossier,
    EmployeePublic,
    EmployeeUpdate,
    Paginated,
    TimelineEvent,
)
from app.services.interaction_report import InteractionReportService
from app.services.tracking_service import decrypt_payload
from app.services.vonage_service import is_e164_phone

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/employees",
    tags=["employees"],
    dependencies=[Depends(rate_limit(scope="employees"))],
)

MAX_CSV_BYTES = 5 * 1024 * 1024
REQUIRED_CSV_COLUMNS = {"email", "first_name"}


async def _get_employee(
    db: AsyncSession, org_id: uuid.UUID, employee_id: uuid.UUID
) -> HumanAsset:
    """Load an employee, asserting it belongs to the organization.

    Raises:
        HTTPException: 404 when not found.
    """
    employee = await db.get(HumanAsset, employee_id)
    if employee is None or employee.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.get("", response_model=Paginated[EmployeePublic], summary="List employees")
async def list_employees(
    org_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    search: str | None = Query(None, max_length=200),
    department: str | None = Query(None, max_length=100),
    is_active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> Paginated[EmployeePublic]:
    """Return a paginated, filterable list of employees.

    Args:
        org_id: Organization id.
        page: 1-based page number.
        per_page: Page size.
        search: Case-insensitive match on name or email.
        department: Exact department filter.
        is_active: Active-flag filter.
        db: Active session.
        organization: Resolved organization (access-checked).
        user: Authenticated user.

    Returns:
        A page of employees.
    """
    filters = [HumanAsset.organization_id == org_id]
    if search:
        pattern = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(HumanAsset.email).like(pattern),
                func.lower(HumanAsset.first_name).like(pattern),
                func.lower(HumanAsset.last_name).like(pattern),
                func.lower(func.coalesce(HumanAsset.department, "")).like(pattern),
            )
        )
    if department:
        filters.append(HumanAsset.department == department)
    if is_active is not None:
        filters.append(HumanAsset.is_active.is_(is_active))

    total = await db.scalar(select(func.count(HumanAsset.id)).where(*filters)) or 0
    rows = (
        await db.execute(
            select(HumanAsset)
            .where(*filters)
            .order_by(HumanAsset.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    return Paginated[EmployeePublic](
        items=[EmployeePublic.model_validate(row) for row in rows],
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)) if total else 0,
    )


@router.post(
    "",
    response_model=EmployeePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create an employee",
)
async def create_employee(
    org_id: uuid.UUID,
    payload: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> EmployeePublic:
    """Create a single employee.

    Args:
        org_id: Organization id.
        payload: Employee data.
        db: Active session.
        organization: Resolved organization.
        user: Authenticated user (admin/manager).

    Returns:
        The created employee.

    Raises:
        HTTPException: 409 when the email already exists in the organization.
    """
    existing = await db.scalar(
        select(HumanAsset).where(
            HumanAsset.organization_id == org_id,
            func.lower(HumanAsset.email) == payload.email.lower(),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An employee with this email exists"
        )
    data = payload.model_dump()
    data["email"] = payload.email.lower()
    employee = HumanAsset(organization_id=org_id, **data)
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    logger.info("employee_created", employee_id=str(employee.id), org_id=str(org_id))
    return EmployeePublic.model_validate(employee)


@router.post(
    "/bulk",
    response_model=BulkImportResult,
    summary="Bulk import employees from a CSV file",
)
async def bulk_import(
    org_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> BulkImportResult:
    """Import employees from a CSV upload.

    The CSV must have a header row containing at least ``email`` and
    ``first_name``.  Recognised columns: ``email``, ``first_name``,
    ``last_name``, ``department``, ``job_title``, ``access_level``, ``phone``.

    Args:
        org_id: Organization id.
        file: The uploaded CSV file.
        db: Active session.
        organization: Resolved organization.
        user: Authenticated user.

    Returns:
        Counts of created/updated/skipped rows plus per-row errors.

    Raises:
        HTTPException: 400 for an oversized, malformed or headerless CSV.
    """
    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="CSV exceeds the 5 MB limit",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to decode CSV file"
            ) from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV has no header row")
    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    if not REQUIRED_CSV_COLUMNS.issubset(headers):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must contain at least 'email' and 'first_name' columns",
        )

    created = updated = skipped = 0
    errors: list[str] = []

    existing_rows = (
        await db.execute(select(HumanAsset).where(HumanAsset.organization_id == org_id))
    ).scalars().all()
    by_email = {row.email.lower(): row for row in existing_rows}

    for line_no, row in enumerate(reader, start=2):
        normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        email = normalized.get("email", "")
        first_name = normalized.get("first_name", "")
        if not email or "@" not in email or not first_name:
            errors.append(f"Line {line_no}: missing/invalid email or first_name")
            skipped += 1
            continue
        phone = normalized.get("phone", "")
        if phone and not is_e164_phone(phone):
            errors.append(
                f"Line {line_no}: phone '{phone}' is not in E.164 format "
                "(for example +966500000000)"
            )
            skipped += 1
            continue
        email = email.lower()
        try:
            access_level = int(normalized.get("access_level") or 1)
        except ValueError:
            access_level = 1
        access_level = max(1, min(5, access_level))

        employee = by_email.get(email)
        if employee is None:
            employee = HumanAsset(
                organization_id=org_id,
                email=email,
                first_name=first_name,
                last_name=normalized.get("last_name", ""),
                department=normalized.get("department") or None,
                job_title=normalized.get("job_title") or None,
                phone=normalized.get("phone") or None,
                access_level=access_level,
                is_active=True,
            )
            db.add(employee)
            by_email[email] = employee
            created += 1
        else:
            employee.first_name = first_name or employee.first_name
            if normalized.get("last_name"):
                employee.last_name = normalized["last_name"]
            if normalized.get("department"):
                employee.department = normalized["department"]
            if normalized.get("job_title"):
                employee.job_title = normalized["job_title"]
            if normalized.get("phone"):
                employee.phone = normalized["phone"]
            employee.access_level = access_level
            updated += 1

    await db.commit()
    logger.info(
        "employees_bulk_imported",
        org_id=str(org_id),
        created=created,
        updated=updated,
        skipped=skipped,
    )
    return BulkImportResult(created=created, updated=updated, skipped=skipped, errors=errors[:100])


@router.get("/{employee_id}", response_model=EmployeePublic, summary="Get an employee")
async def get_employee(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> EmployeePublic:
    """Return a single employee."""
    employee = await _get_employee(db, org_id, employee_id)
    return EmployeePublic.model_validate(employee)


@router.put("/{employee_id}", response_model=EmployeePublic, summary="Update an employee")
async def update_employee(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> EmployeePublic:
    """Apply a partial update to an employee.

    Raises:
        HTTPException: 409 when changing to an email already in use.
    """
    employee = await _get_employee(db, org_id, employee_id)
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        new_email = data["email"].lower()
        clash = await db.scalar(
            select(HumanAsset).where(
                HumanAsset.organization_id == org_id,
                func.lower(HumanAsset.email) == new_email,
                HumanAsset.id != employee_id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Another employee uses this email"
            )
        data["email"] = new_email
    for field, value in data.items():
        setattr(employee, field, value)
    await db.commit()
    await db.refresh(employee)
    logger.info("employee_updated", employee_id=str(employee_id))
    return EmployeePublic.model_validate(employee)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an employee",
    response_model=None,
)
async def delete_employee(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin")),
) -> None:
    """Delete an employee."""
    employee = await _get_employee(db, org_id, employee_id)
    await db.delete(employee)
    await db.commit()
    logger.info("employee_deleted", employee_id=str(employee_id))


@router.get(
    "/{employee_id}/dossier",
    response_model=EmployeeDossier,
    summary="Everything recorded about one employee",
)
async def employee_dossier(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> EmployeeDossier:
    """Return the employee's complete training dossier.

    Contains the profile, an aggregate summary, one record per campaign and the
    merged interaction ledger — every event with microsecond timestamps, the IP
    and device it came from, and every value the employee typed (decrypted from
    encrypted storage).
    """
    employee = await _get_employee(db, org_id, employee_id)
    data = await InteractionReportService().employee_dossier(employee, db)
    return EmployeeDossier.model_validate(data)


@router.get(
    "/{employee_id}/timeline",
    response_model=list[TimelineEvent],
    summary="Return an employee's chronological engagement timeline",
)
async def employee_timeline(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[TimelineEvent]:
    """Build the employee's timeline from tracking + campaign data.

    Returns:
        Events ordered oldest first (sent, opened, clicked, completed).
    """
    await _get_employee(db, org_id, employee_id)
    rows = (
        await db.execute(
            select(EmailTracking, EmailCampaign)
            .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
            .where(EmailTracking.employee_id == employee_id)
            .order_by(EmailTracking.created_at.asc())
        )
    ).all()

    events: list[TimelineEvent] = []

    def _add(event_type: str, when: datetime | None, campaign: EmailCampaign, details: dict) -> None:
        if when is None:
            return
        events.append(
            TimelineEvent(
                event_type=event_type,
                timestamp=when,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                details=details,
            )
        )

    for tracking, campaign in rows:
        channel = (tracking.channel or campaign.channel or "email").strip().lower()
        details = {"channel": channel}
        _add("campaign_assigned", tracking.created_at, campaign, details)
        if channel == "email":
            _add("email_sent", tracking.sent_at, campaign, {**details, "message_id": tracking.provider_message_id})
            _add("email_delivered", tracking.delivered_at, campaign, details)
        else:
            _add("message_sent", tracking.sent_at, campaign, {**details, "message_id": tracking.provider_message_id})
            _add("message_delivered", tracking.delivered_at, campaign, details)
            _add("message_read", tracking.read_at, campaign, details)
        _add("email_opened", tracking.opened_at, campaign, {**details, "open_count": tracking.open_count})
        _add("link_clicked", tracking.clicked_at, campaign, {**details, "click_count": tracking.click_count})
        _add("training_form_viewed", tracking.viewed_at, campaign, details)
        if tracking.submitted_at is not None:
            _add(
                "credentials_submitted",
                tracking.submitted_at,
                campaign,
                {
                    **details,
                    "identifier": tracking.submitted_identifier,
                    "password_length": tracking.password_length,
                    # Verbatim, decrypted evidence of what was typed.
                    "values": decrypt_payload(tracking.submitted_payload_encrypted)
                    or (tracking.submitted_fields or {}),
                    "submission_count": tracking.submission_count,
                },
            )
        _add(
            "phishing_reported",
            tracking.reported_at,
            campaign,
            {**details, "source": "training_page"},
        )
        _add("training_completed", tracking.completed_at, campaign, details)

    events.sort(key=lambda event: event.timestamp)
    return events
