"""Employee (human asset) endpoints."""
from __future__ import annotations

import csv
import io
import math
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import (
    get_organization_or_404,
    rate_limit,
    require_permissions,
    require_roles,
)
from app.logging_config import get_logger
from app.models import (
    Department,
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    MonthlyArchive,
    User,
)
from app.schemas import (
    BulkImportResult,
    EmployeeCreate,
    EmployeeDossier,
    EmployeePublic,
    EmployeeUpdate,
    MonthlyArchiveMonth,
    MonthlyArchiveResponse,
    MonthlyArchiveRow,
    MonthlyArchiveRunRequest,
    MonthlyArchiveRunResult,
    MonthlyEloPoint,
    Paginated,
    TimelineEvent,
)
from app.services.audit_service import log_audit
from app.services.elo_engine import awareness_level_ar, awareness_level_for_elo
from app.services.encryption_service import try_decrypt_text
from app.services.employee_service import (
    archive_monthly_scores,
    build_certificate_pdf,
    build_certificates_zip,
    build_employee_report_pdf,
    build_monthly_report_pdf,
    validate_month,
)
from app.services.interaction_report import InteractionReportService
from app.services.tracking_service import decrypt_payload
from app.services.textbee_service import is_e164_phone

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/employees",
    tags=["employees"],
    dependencies=[Depends(rate_limit(scope="employees"))],
)

MAX_CSV_BYTES = 5 * 1024 * 1024
REQUIRED_CSV_COLUMNS = {"email", "first_name"}


def _employee_snapshot(employee: HumanAsset) -> dict:
    """Return the auditable, non-secret view of an employee row."""
    return {
        "email": employee.email,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "department": employee.department,
        "job_title": employee.job_title,
        "phone": employee.phone,
        "access_level": employee.access_level,
        "is_active": employee.is_active,
        "is_on_leave": employee.is_on_leave,
        "organization_id": str(employee.organization_id),
    }


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
    user: User = Depends(require_permissions("employees.view")),
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


@router.get(
    "/departments",
    response_model=list[dict],
    summary="List departments with employee counts",
)
async def list_departments(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
) -> list[dict]:
    """Return the organization's distinct departments and their headcounts.

    Departments are entered by HR imports and are therefore free-form; the
    campaign wizard uses this list to segment targets server-side.
    """
    rows = (
        await db.execute(
            select(HumanAsset.department, func.count(HumanAsset.id))
            .where(
                HumanAsset.organization_id == org_id,
                HumanAsset.department.is_not(None),
                HumanAsset.department != "",
            )
            .group_by(HumanAsset.department)
            .order_by(HumanAsset.department.asc())
        )
    ).all()
    return [
        {"department": department, "count": int(count)}
        for department, count in rows
        if department
    ]


@router.post(
    "",
    response_model=EmployeePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create an employee",
)
async def create_employee(
    org_id: uuid.UUID,
    payload: EmployeeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
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
    await db.flush()
    log_audit(
        db,
        user=user,
        action="CREATE",
        target_table="human_assets",
        target_id=str(employee.id),
        new=_employee_snapshot(employee),
        request=request,
    )
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
    user: User = Depends(require_permissions("employees.manage")),
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


# --------------------------------------------------------------------------- #
# Monthly archives, certificates and reports (modules 2 and 5)
# --------------------------------------------------------------------------- #
async def _load_archive_payloads(
    db: AsyncSession, org_id: uuid.UUID, month_year: str
) -> list[dict]:
    """Load archived rows joined with their employee profile."""
    rows = (
        await db.execute(
            select(MonthlyArchive, HumanAsset)
            .join(HumanAsset, HumanAsset.id == MonthlyArchive.employee_id)
            .where(
                HumanAsset.organization_id == org_id,
                MonthlyArchive.month_year == month_year,
            )
            .order_by(
                MonthlyArchive.final_elo_score.asc(),
                HumanAsset.first_name.asc(),
                HumanAsset.last_name.asc(),
            )
        )
    ).all()
    payloads: list[dict] = []
    for archive, employee in rows:
        payloads.append(
            {
                "employee": employee,
                "employee_id": employee.id,
                "employee_name": employee.full_name,
                "email": employee.email,
                "department": employee.department,
                "month_year": archive.month_year,
                "final_elo_score": int(archive.final_elo_score),
                "total_reports": int(archive.total_reports or 0),
                "total_clicks": int(archive.total_clicks or 0),
                "total_submissions": int(archive.total_submissions or 0),
                "awareness_level": awareness_level_for_elo(archive.final_elo_score),
                "awareness_level_ar": awareness_level_ar(archive.final_elo_score),
                "is_blacklisted": bool(employee.is_blacklisted),
            }
        )
    return payloads


def _archive_row(payload: dict) -> MonthlyArchiveRow:
    """Convert an internal payload to the public archive row schema."""
    return MonthlyArchiveRow(
        **{key: value for key, value in payload.items() if key != "employee"}
    )


@router.get(
    "/monthly-elo-trend",
    response_model=list[MonthlyEloPoint],
    summary="Monthly average Elo trend",
)
async def monthly_elo_trend(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
) -> list[MonthlyEloPoint]:
    """Return one average-Elo point per archived month, oldest first."""
    rows = (
        await db.execute(
            select(
                MonthlyArchive.month_year,
                func.avg(MonthlyArchive.final_elo_score),
                func.count(MonthlyArchive.id),
            )
            .join(HumanAsset, HumanAsset.id == MonthlyArchive.employee_id)
            .where(HumanAsset.organization_id == org_id)
            .group_by(MonthlyArchive.month_year)
            .order_by(MonthlyArchive.month_year.asc())
        )
    ).all()
    return [
        MonthlyEloPoint(
            month_year=row[0],
            average_elo=round(float(row[1] or 0), 1),
            employee_count=int(row[2] or 0),
        )
        for row in rows
    ]


@router.get(
    "/monthly-archives",
    response_model=MonthlyArchiveResponse,
    summary="Monthly archive rows",
)
async def monthly_archives(
    org_id: uuid.UUID,
    month: str | None = Query(
        None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
) -> MonthlyArchiveResponse:
    """Return available archive months and the selected month's rows."""
    month_rows = (
        await db.execute(
            select(
                MonthlyArchive.month_year,
                func.count(MonthlyArchive.id),
                func.avg(MonthlyArchive.final_elo_score),
            )
            .join(HumanAsset, HumanAsset.id == MonthlyArchive.employee_id)
            .where(HumanAsset.organization_id == org_id)
            .group_by(MonthlyArchive.month_year)
            .order_by(MonthlyArchive.month_year.desc())
        )
    ).all()
    months = [
        MonthlyArchiveMonth(
            month_year=row[0],
            employee_count=int(row[1] or 0),
            average_elo=round(float(row[2] or 0), 1),
        )
        for row in month_rows
    ]
    selected = month or (months[0].month_year if months else None)
    payloads = (
        await _load_archive_payloads(db, org_id, selected) if selected else []
    )
    average = (
        round(
            sum(row["final_elo_score"] for row in payloads) / len(payloads),
            1,
        )
        if payloads
        else None
    )
    return MonthlyArchiveResponse(
        month=selected,
        months=months,
        rows=[_archive_row(row) for row in payloads],
        average_elo=average,
    )


@router.post(
    "/monthly-archives/run",
    response_model=MonthlyArchiveRunResult,
    summary="Run the monthly archive now (admin)",
)
async def run_monthly_archive(
    org_id: uuid.UUID,
    payload: MonthlyArchiveRunRequest,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
    _admin: User = Depends(require_roles("admin")),
) -> MonthlyArchiveRunResult:
    """Manually snapshot the month and reset live Elo scores.

    This is the local/demo path for environments without a Celery worker; the
    scheduled task calls the same service function.
    """
    result = await archive_monthly_scores(
        db,
        month_year=payload.month,
        force=payload.force,
        organization_id=org_id,
    )
    return MonthlyArchiveRunResult(**result)


@router.get(
    "/monthly-report",
    summary="Download the monthly PDF report",
)
async def monthly_report(
    org_id: uuid.UUID,
    month: str = Query(
        ..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("reports.view")),
) -> Response:
    """Render the monthly archive report as a PDF."""
    validate_month(month)
    payloads = await _load_archive_payloads(db, org_id, month)
    if not payloads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No monthly archive exists for {month}",
        )
    pdf = build_monthly_report_pdf(organization.name, month, payloads)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="monthly-report-{month}.pdf"'
        },
    )


@router.get(
    "/certificates.zip",
    summary="Download all monthly certificates as a ZIP",
)
async def certificates_zip(
    org_id: uuid.UUID,
    month: str = Query(
        ..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("reports.view")),
) -> Response:
    """Bundle every archived employee certificate for a month into a ZIP."""
    validate_month(month)
    payloads = await _load_archive_payloads(db, org_id, month)
    if not payloads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No monthly archive exists for {month}",
        )
    archive = build_certificates_zip(month, payloads)
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="certificates-{month}.zip"'
        },
    )


@router.get(
    "/{employee_id}/certificate",
    summary="Download one employee's monthly certificate",
)
async def employee_certificate(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    month: str | None = Query(
        None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM (default: current month)"
    ),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("reports.view")),
) -> Response:
    """Render one employee's certificate as a PDF.

    When ``month`` is omitted the current UTC month is used.  If that month has
    already been archived the immutable snapshot is printed; otherwise the live
    Elo score and counters are used, so a certificate can always be produced
    without waiting for the month-end job.
    """
    if month is not None:
        validate_month(month)
    employee = await _get_employee(db, org_id, employee_id)
    certificate_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    archive = await db.scalar(
        select(MonthlyArchive).where(
            MonthlyArchive.employee_id == employee.id,
            MonthlyArchive.month_year == certificate_month,
        )
    )
    if archive is not None:
        final_score = int(archive.final_elo_score)
        reports = int(archive.total_reports or 0)
        clicks = int(archive.total_clicks or 0)
        submissions = int(archive.total_submissions or 0)
    else:
        final_score = int(employee.elo_score or 0)
        reports = int(employee.total_reports or 0)
        clicks = int(employee.total_clicks or 0)
        submissions = int(employee.total_credential_submissions or 0)
    pdf = build_certificate_pdf(
        employee,
        certificate_month,
        final_score,
        reports,
        clicks,
        submissions,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="certificate-{employee.id}-{certificate_month}.pdf"'
            ),
            "Cache-Control": "no-store",
        },
    )


#: Field-name tokens whose value must never leave the server in clear text.
SENSITIVE_FIELD_TOKENS = ("pass", "secret", "pin", "otp", "token", "cvv", "code")


def _masked_values(values: dict | None) -> dict[str, object]:
    """Return ``values`` with credential-like fields replaced by bullets."""
    masked: dict[str, object] = {}
    for key, value in (values or {}).items():
        lowered = str(key).lower()
        masked[key] = "••••••" if any(token in lowered for token in SENSITIVE_FIELD_TOKENS) else value
    return masked


@router.get(
    "/{employee_id}/intelligence",
    summary="Aggregated intelligence profile for one employee",
)
async def employee_intelligence(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500, description="Ledger events to return"),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
) -> dict:
    """Return everything the Employee Intelligence Hub needs in one call.

    One request replaces the five the old UI issued (profile, dossier, timeline,
    submissions, archives) and guarantees they are mutually consistent because
    they are read in the same transaction.

    Returns:
        ``employee``, ``elo``, ``summary``, ``journeys``, ``events``,
        ``submissions`` and ``certificates``.
    """
    employee = await _get_employee(db, org_id, employee_id)
    dossier = await InteractionReportService().employee_dossier(employee, db)

    archives = (
        await db.execute(
            select(MonthlyArchive)
            .where(MonthlyArchive.employee_id == employee.id)
            .order_by(MonthlyArchive.month_year.desc())
        )
    ).scalars().all()
    department = (
        await db.get(Department, employee.department_id)
        if employee.department_id
        else None
    )

    events = dossier["events"]
    recent_events = events[-limit:]
    submissions = [
        {
            "campaign_id": str(item.get("campaign_id")) if item.get("campaign_id") else None,
            "campaign_name": item.get("campaign_name"),
            "occurred_at": item.get("occurred_at"),
            "ip_address": item.get("ip_address"),
            "user_agent": item.get("user_agent"),
            "password_length": item.get("password_length"),
            "client": item.get("client"),
            "values": _masked_values(item.get("values")),
        }
        for record in dossier["campaigns"]
        for item in record["submissions"]
    ][-limit:]

    campaign_ids = {
        event["campaign_id"] for event in events if event.get("campaign_id") is not None
    }
    journey_map = (
        dict(
            (
                await db.execute(
                    select(EmailCampaign.id, EmailCampaign.journey_id).where(
                        EmailCampaign.id.in_(campaign_ids)
                    )
                )
            ).all()
        )
        if campaign_ids
        else {}
    )
    journeys = [
        {
            "campaign_id": str(record["campaign_id"]),
            "journey_id": str(journey_map.get(record["campaign_id"]))
            if journey_map.get(record["campaign_id"])
            else None,
            "campaign_name": record["campaign_name"],
            "channel": record["channel"],
            "status": record["status"],
            "sent_at": record["sent_at"],
            "clicked_at": record["clicked_at"],
            "submitted_at": record["submitted_at"],
            "completed_at": record["completed_at"],
        }
        for record in dossier["campaigns"]
    ]

    score = int(employee.elo_score or 0)
    return {
        "employee": {
            "id": str(employee.id),
            "organization_id": str(employee.organization_id),
            "full_name": employee.full_name,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "email": employee.email,
            "phone": employee.phone,
            "job_title": employee.job_title,
            "department": employee.department,
            "department_id": str(employee.department_id) if employee.department_id else None,
            "department_name": department.name if department is not None else None,
            "is_active": employee.is_active,
            "is_blacklisted": employee.is_blacklisted,
            "blacklist_reason": employee.blacklist_reason,
            "under_enhanced_monitoring": employee.under_enhanced_monitoring,
            "requires_mandatory_training": employee.requires_mandatory_training,
            "created_at": employee.created_at,
        },
        "elo": {
            "score": score,
            "level_en": awareness_level_for_elo(score),
            "level_ar": awareness_level_ar(score),
            "category": employee.behavioral_category,
            "immunity_score": (
                float(employee.immunity_score)
                if employee.immunity_score is not None
                else None
            ),
            "total_clicks": int(employee.total_clicks or 0),
            "total_reports": int(employee.total_reports or 0),
            "total_submissions": int(employee.total_credential_submissions or 0),
        },
        "summary": dossier["summary"],
        "journeys": journeys,
        "events": recent_events,
        "submissions": submissions,
        "certificates": [
            {
                "month_year": archive.month_year,
                "final_elo_score": int(archive.final_elo_score),
                "total_reports": int(archive.total_reports or 0),
                "total_clicks": int(archive.total_clicks or 0),
                "total_submissions": int(archive.total_submissions or 0),
                "level_ar": awareness_level_ar(int(archive.final_elo_score)),
                "level_en": awareness_level_for_elo(int(archive.final_elo_score)),
                "download_url": (
                    f"/api/v1/organizations/{org_id}/employees/{employee.id}"
                    f"/certificate?month={archive.month_year}"
                ),
            }
            for archive in archives
        ],
    }


@router.get(
    "/{employee_id}/report-pdf",
    summary="Download one employee's detailed intelligence report (PDF)",
)
async def employee_report_pdf(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("reports.view")),
) -> Response:
    """Render the employee's full profile report as a PDF."""
    employee = await _get_employee(db, org_id, employee_id)
    dossier = await InteractionReportService().employee_dossier(employee, db)
    archives = (
        await db.execute(
            select(MonthlyArchive)
            .where(MonthlyArchive.employee_id == employee.id)
            .order_by(MonthlyArchive.month_year.desc())
        )
    ).scalars().all()
    submissions = [
        {
            **item,
            "values": _masked_values(item.get("values")),
        }
        for record in dossier["campaigns"]
        for item in record["submissions"]
    ]
    try:
        pdf = build_employee_report_pdf(
            employee,
            organization.name,
            summary=dossier["summary"],
            campaigns=dossier["campaigns"],
            events=dossier["events"],
            submissions=submissions,
            certificates=[
                {
                    "month_year": archive.month_year,
                    "final_elo_score": int(archive.final_elo_score),
                    "total_reports": int(archive.total_reports or 0),
                    "total_clicks": int(archive.total_clicks or 0),
                    "total_submissions": int(archive.total_submissions or 0),
                }
                for archive in archives
            ],
        )
    except Exception as exc:  # noqa: BLE001 - a PDF failure must not 500 quietly
        logger.exception(
            "employee_report_pdf_failed",
            employee_id=str(employee.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate the employee report",
        ) from exc
    logger.info(
        "employee_report_pdf_generated",
        employee_id=str(employee.id),
        organization_id=str(org_id),
        bytes=len(pdf),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="employee-report-{employee.id}.pdf"'
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{employee_id}", response_model=EmployeePublic, summary="Get an employee")
async def get_employee(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.view")),
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
    user: User = Depends(require_permissions("employees.manage")),
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.delete")),
) -> None:
    """Delete an employee and record the last known state in the audit trail."""
    employee = await _get_employee(db, org_id, employee_id)
    log_audit(
        db,
        user=user,
        action="DELETE",
        target_table="human_assets",
        target_id=str(employee.id),
        old=_employee_snapshot(employee),
        request=request,
    )
    await db.delete(employee)
    await db.commit()
    logger.info("employee_deleted", employee_id=str(employee_id))


@router.get(
    "/{employee_id}/sensitive",
    summary="Decrypted employee PII (admin only)",
)
async def employee_sensitive(
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_permissions("employees.manage")),
    _admin: User = Depends(require_roles("admin")),
) -> dict:
    """Return the PII decrypted from the ``BYTEA`` columns.

    The general employee payloads stay redaction-friendly; this dedicated,
    admin-only route is the single place where the sealed e-mail/phone are
    returned in plaintext.  It falls back to the legacy columns for rows that
    predate the encryption migration.
    """
    employee = await _get_employee(db, org_id, employee_id)
    return {
        "employee_id": str(employee.id),
        "email": try_decrypt_text(employee.email_encrypted) or employee.email,
        "phone": try_decrypt_text(employee.phone_encrypted) or employee.phone,
        "encrypted_at_rest": bool(employee.email_encrypted),
    }


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
    user: User = Depends(require_permissions("employees.view")),
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
    user: User = Depends(require_permissions("employees.view")),
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
