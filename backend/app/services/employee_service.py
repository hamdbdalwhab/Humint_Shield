"""Employee Elo synchronisation, guardrails, monthly archives and PDF output.

This service is the single place where a behavioural event changes an
employee's Elo rating.  Tracking code calls :func:`apply_elo_action` so the
channel weight, campaign difficulty and action impact are always applied
consistently and the resulting delta can be written to the interaction ledger
(profile timeline/history).

It also owns the module 2/4 monthly lifecycle:

* snapshot the month into ``monthly_archives``;
* compare the snapshot with the previous month and blacklist repeated failures;
* reset the live Elo rating to 1000;
* render certificates, the monthly PDF report and the certificates ZIP.
"""
from __future__ import annotations

import calendar
import io
import math
import re
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    MonthlyArchive,
    Organization,
    PhishingReport,
    TrainingInteraction,
)
from app.services.elo_engine import (
    INITIAL_ELO,
    apply_elo_delta,
    awareness_level_ar,
    awareness_level_for_elo,
    clamp_elo,
    smart_elo_delta,
)

logger = get_logger(__name__)

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# --------------------------------------------------------------------------- #
# Elo synchronisation
# --------------------------------------------------------------------------- #
async def campaign_difficulty(
    db: AsyncSession, campaign: EmailCampaign | None
) -> int | None:
    """Return the difficulty of a campaign's template, when available."""
    if campaign is None or campaign.template_id is None:
        return None
    template = await db.get(EmailTemplate, campaign.template_id)
    return int(template.difficulty_level) if template is not None else None


async def tracking_difficulty(
    db: AsyncSession, tracking: EmailTracking
) -> int | None:
    """Return the difficulty of the template used for one tracking row."""
    template_id = tracking.template_id
    if template_id is None:
        campaign = await db.get(EmailCampaign, tracking.campaign_id)
        template_id = campaign.template_id if campaign is not None else None
    if template_id is None:
        return None
    template = await db.get(EmailTemplate, template_id)
    return int(template.difficulty_level) if template is not None else None


async def apply_elo_action(
    db: AsyncSession,
    employee: HumanAsset,
    tracking: EmailTracking,
    action: str,
) -> int:
    """Apply one smart-scored action to an employee and return the delta.

    The caller writes the returned delta into the interaction ledger, which is
    what makes the score change visible immediately on the employee profile and
    timeline without a second write path.
    """
    difficulty = await tracking_difficulty(db, tracking)
    delta = smart_elo_delta(tracking.channel, action, difficulty)
    employee.elo_score = apply_elo_delta(employee.elo_score, delta)
    return delta


# --------------------------------------------------------------------------- #
# Cooldown + blacklist guardrails (modules 3 and 4)
# --------------------------------------------------------------------------- #
def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise SQLite's naive timestamps to aware UTC datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_send_blockers(
    db: AsyncSession,
    organization: Organization,
    employee_ids: Iterable[uuid.UUID],
    *,
    exclude_campaign_id: uuid.UUID | None = None,
    is_mandatory_training: bool = False,
) -> dict[uuid.UUID, dict[str, Any]]:
    """Return employees that must not receive a normal campaign.

    Each value is the exact block payload contract::

        {"status": "blocked", "reason": "cooldown_active",
         "last_campaign_id": "..."}

    plus display fields used by the warning modal.  Mandatory-training
    campaigns bypass both the cooldown and the repeated-failure blacklist.
    """
    if is_mandatory_training:
        return {}
    ids = list(dict.fromkeys(employee_ids))
    if not ids:
        return {}

    employees = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == organization.id,
                HumanAsset.id.in_(ids),
            )
        )
    ).scalars().all()
    by_id = {employee.id: employee for employee in employees}

    blockers: dict[uuid.UUID, dict[str, Any]] = {}
    for employee in employees:
        if employee.is_blacklisted:
            blockers[employee.id] = {
                "employee_id": employee.id,
                "email": employee.email,
                "name": employee.full_name,
                "status": "blocked",
                "reason": "blacklisted_repeated_failure",
                "last_campaign_id": None,
                "last_campaign_name": None,
                "last_campaign_at": None,
                "days_remaining": None,
            }

    cooldown_days = int(organization.campaign_cooldown_days or 0)
    if cooldown_days <= 0:
        return blockers

    statement = (
        select(EmailTracking, EmailCampaign)
        .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
        .where(
            EmailCampaign.organization_id == organization.id,
            EmailTracking.employee_id.in_(ids),
            EmailTracking.sent_at.is_not(None),
            EmailCampaign.status.in_(("active", "completed")),
        )
    )
    if exclude_campaign_id is not None:
        statement = statement.where(EmailCampaign.id != exclude_campaign_id)
    statement = statement.order_by(EmailTracking.sent_at.desc())
    rows = (await db.execute(statement)).all()

    now = datetime.now(timezone.utc)
    seen: set[uuid.UUID] = set()
    for tracking, campaign in rows:
        employee_id = tracking.employee_id
        if employee_id is None or employee_id in seen:
            continue
        seen.add(employee_id)
        last_at = _as_utc(tracking.sent_at)
        if last_at is None:
            continue
        elapsed_days = max(0.0, (now - last_at).total_seconds() / 86400.0)
        if elapsed_days >= cooldown_days:
            continue
        if employee_id in blockers:
            continue
        employee = by_id.get(employee_id)
        blockers[employee_id] = {
            "employee_id": employee_id,
            "email": employee.email if employee else "unknown",
            "name": employee.full_name if employee else "unknown",
            "status": "blocked",
            "reason": "cooldown_active",
            "last_campaign_id": campaign.id,
            "last_campaign_name": campaign.name,
            "last_campaign_at": last_at,
            "days_remaining": max(0, math.ceil(cooldown_days - elapsed_days)),
        }
    return blockers


# --------------------------------------------------------------------------- #
# Month helpers
# --------------------------------------------------------------------------- #
def validate_month(month_year: str) -> str:
    """Validate a ``YYYY-MM`` value and return it unchanged."""
    value = (month_year or "").strip()
    if not MONTH_RE.match(value):
        raise ValueError("month must use YYYY-MM format")
    return value


def month_bounds(month_year: str) -> tuple[datetime, datetime]:
    """Return the inclusive-start/exclusive-end UTC bounds of a month."""
    value = validate_month(month_year)
    year, month = (int(part) for part in value.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def current_month_year(now: datetime | None = None) -> str:
    """Return the current UTC month in ``YYYY-MM`` form."""
    moment = _as_utc(now) or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def is_last_day_of_month(day: date | None = None) -> bool:
    """Return ``True`` when ``day`` is the final calendar day of its month."""
    value = day or datetime.now(timezone.utc).date()
    return value.day == calendar.monthrange(value.year, value.month)[1]


# --------------------------------------------------------------------------- #
# Monthly archive task body (module 2 + 4)
# --------------------------------------------------------------------------- #
async def archive_monthly_scores(
    db: AsyncSession,
    *,
    month_year: str | None = None,
    force: bool = False,
    now: datetime | None = None,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Snapshot employees, apply the blacklist rule and reset Elo to 1000.

    Args:
        db: Active session.
        month_year: Explicit ``YYYY-MM`` to archive.  Defaults to the current
            UTC month.
        force: Archive even when the current day is not the last day of the
            month.  The Celery beat job runs daily and uses this check so it is
            idempotent on every other day.
        now: Injectable clock for tests.
        organization_id: When provided, only that organization is archived.
            The scheduled task omits it and archives every organization.

    Returns:
        A summary dictionary.
    """
    moment = _as_utc(now) or datetime.now(timezone.utc)
    target_month = validate_month(month_year) if month_year else current_month_year(moment)
    if month_year is None and not force and not is_last_day_of_month(moment.date()):
        logger.info("monthly_archive_skipped_not_last_day", month=target_month)
        return {
            "status": "skipped",
            "reason": "not_last_day",
            "month": target_month,
            "archived": 0,
            "blacklisted": 0,
            "reset": 0,
        }

    start, end = month_bounds(target_month)
    employee_statement = select(HumanAsset)
    if organization_id is not None:
        employee_statement = employee_statement.where(
            HumanAsset.organization_id == organization_id
        )
    employees = (await db.execute(employee_statement)).scalars().all()
    if not employees:
        return {
            "status": "ok",
            "month": target_month,
            "archived": 0,
            "blacklisted": 0,
            "reset": 0,
        }

    employee_ids = [employee.id for employee in employees]

    # The interaction ledger is the source of truth for monthly behaviour: it
    # stores one row per event, so a click in October and another in November
    # land in the correct archive instead of being collapsed by the cumulative
    # counters on ``tracking_events``.
    click_events = {
        "link_click",
        "usb_opened",
    }
    submission_events = {
        "form_submitted",
        "credential_submitted",
        "otp_submitted",
        "credential_disclosed",
        "financial_fraud",
        "hid_executed",
        "qr_credential_submitted",
    }
    event_rows = (
        await db.execute(
            select(
                TrainingInteraction.employee_id,
                TrainingInteraction.event_type,
                func.count(TrainingInteraction.id),
            )
            .where(
                TrainingInteraction.employee_id.in_(employee_ids),
                TrainingInteraction.occurred_at >= start,
                TrainingInteraction.occurred_at < end,
            )
            .group_by(TrainingInteraction.employee_id, TrainingInteraction.event_type)
        )
    ).all()

    clicks: dict[uuid.UUID, int] = {}
    submissions: dict[uuid.UUID, int] = {}
    for employee_id, event_type, count in event_rows:
        value = int(count or 0)
        if event_type in click_events:
            clicks[employee_id] = clicks.get(employee_id, 0) + value
        elif event_type in submission_events:
            submissions[employee_id] = submissions.get(employee_id, 0) + value

    # Reports are counted from the report table rather than the interaction
    # ledger: an administrator confirming an existing report safe also writes a
    # ledger row, and counting that row would inflate the monthly total.
    report_rows = (
        await db.execute(
            select(PhishingReport.employee_id, func.count(PhishingReport.id))
            .where(
                PhishingReport.employee_id.in_(employee_ids),
                PhishingReport.created_at >= start,
                PhishingReport.created_at < end,
            )
            .group_by(PhishingReport.employee_id)
        )
    ).all()
    reports = {row[0]: int(row[1] or 0) for row in report_rows}

    previous_rows = (
        await db.execute(
            select(MonthlyArchive)
            .where(
                MonthlyArchive.employee_id.in_(employee_ids),
                MonthlyArchive.month_year < target_month,
            )
            .order_by(MonthlyArchive.month_year.desc())
        )
    ).scalars().all()
    previous: dict[uuid.UUID, MonthlyArchive] = {}
    for row in previous_rows:
        previous.setdefault(row.employee_id, row)

    existing_rows = (
        await db.execute(
            select(MonthlyArchive).where(
                MonthlyArchive.month_year == target_month,
                MonthlyArchive.employee_id.in_(employee_ids),
            )
        )
    ).scalars().all()
    existing = {row.employee_id: row for row in existing_rows}

    archived = 0
    blacklisted = 0
    reset = 0
    skipped_existing = 0
    for employee in employees:
        archive = existing.get(employee.id)
        if archive is not None:
            # The snapshot is immutable.  A retry after the first successful
            # run must not overwrite the archived score with the freshly reset
            # 1000, nor reset the live score a second time.
            skipped_existing += 1
            continue

        final_score = clamp_elo(employee.elo_score)
        archive = MonthlyArchive(
            employee_id=employee.id,
            month_year=target_month,
            final_elo_score=final_score,
        )
        db.add(archive)
        archive.total_reports = reports.get(employee.id, 0)
        archive.total_clicks = clicks.get(employee.id, 0)
        archive.total_submissions = submissions.get(employee.id, 0)

        previous_archive = previous.get(employee.id)
        if (
            previous_archive is not None
            and final_score <= int(previous_archive.final_elo_score)
            and final_score < 600
        ):
            if not employee.is_blacklisted:
                blacklisted += 1
            employee.is_blacklisted = True
            employee.blacklist_reason = "repeated_failure"
            employee.blacklisted_at = moment
        elif (
            final_score >= 600
            and employee.is_blacklisted
            and employee.blacklist_reason == "repeated_failure"
        ):
            # A clear improvement above the risk floor lifts the blacklist.
            employee.is_blacklisted = False
            employee.blacklist_reason = None
            employee.blacklisted_at = None

        employee.elo_score = INITIAL_ELO
        archived += 1
        reset += 1

    await db.commit()
    logger.info(
        "monthly_archive_completed",
        month=target_month,
        archived=archived,
        blacklisted=blacklisted,
        reset=reset,
        skipped_existing=skipped_existing,
    )
    return {
        "status": "ok",
        "month": target_month,
        "archived": archived,
        "blacklisted": blacklisted,
        "reset": reset,
        "skipped_existing": skipped_existing,
    }


# --------------------------------------------------------------------------- #
# PDF helpers
# --------------------------------------------------------------------------- #
_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONTS_READY = False

_INK = colors.HexColor("#0B1220")
_MUTED = colors.HexColor("#64748B")
_CYAN = colors.HexColor("#00B8D4")
_NAVY = colors.HexColor("#0F172A")
_GREEN = colors.HexColor("#059669")
_RED = colors.HexColor("#DC2626")
_AMBER = colors.HexColor("#D97706")


def _register_fonts() -> None:
    """Register the bundled Arabic font (Amiri) with a Windows fallback."""
    global _FONT_REGULAR, _FONT_BOLD, _FONTS_READY
    if _FONTS_READY:
        return
    candidates = [
        (
            _ASSET_DIR / "Amiri-Regular.ttf",
            _ASSET_DIR / "Amiri-Bold.ttf",
            "Amiri",
            "Amiri-Bold",
        ),
        (
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            "ReportArabic",
            "ReportArabic-Bold",
        ),
    ]
    for regular_path, bold_path, regular_name, bold_name in candidates:
        try:
            if not regular_path.exists() or not bold_path.exists():
                continue
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
            pdfmetrics.registerFontFamily(
                regular_name,
                normal=regular_name,
                bold=bold_name,
                italic=regular_name,
                boldItalic=bold_name,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the next font
            logger.warning("pdf_font_registration_failed", path=str(regular_path), error=str(exc))
            continue
        _FONT_REGULAR = regular_name
        _FONT_BOLD = bold_name
        _FONTS_READY = True
        return
    logger.warning("pdf_arabic_font_missing", asset_dir=str(_ASSET_DIR))
    _FONTS_READY = True


def _visual(value: Any) -> str:
    """Return shaped visual-order text for ReportLab."""
    text = "" if value is None else str(value)
    if _ARABIC_RE.search(text):
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:  # pragma: no cover - shaping is best effort
            return text
    return text


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    """Build a Paragraph from shaped, XML-escaped text."""
    return Paragraph(escape(_visual(value)), style)


def _style(
    *,
    size: float = 9,
    bold: bool = False,
    color: colors.Color | None = None,
    align: int = TA_RIGHT,
    leading: float | None = None,
) -> ParagraphStyle:
    """Build a compact RTL paragraph style."""
    _register_fonts()
    return ParagraphStyle(
        name=f"employee-report-{size}-{bold}-{id(color)}",
        fontName=_FONT_BOLD if bold else _FONT_REGULAR,
        fontSize=size,
        leading=leading or size * 1.5,
        textColor=color or _INK,
        alignment=align,
    )


def _safe_filename(value: str) -> str:
    """Return a filesystem-safe ASCII fragment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "employee").strip("._")
    return cleaned[:60] or "employee"


def build_certificate_pdf(
    employee: HumanAsset,
    month_year: str,
    final_elo_score: int,
    total_reports: int,
    total_clicks: int,
    total_submissions: int,
) -> bytes:
    """Render one employee's monthly awareness certificate as PDF bytes."""
    _register_fonts()
    score = clamp_elo(final_elo_score)
    level_en = awareness_level_for_elo(score)
    level_ar = awareness_level_ar(score)

    buffer = io.BytesIO()
    page = landscape(A4)
    width, height = page
    pdf = canvas.Canvas(buffer, pagesize=page)

    # Background and double border.
    pdf.setFillColor(colors.HexColor("#08111F"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(_CYAN)
    pdf.setLineWidth(2)
    pdf.rect(14 * mm, 14 * mm, width - 28 * mm, height - 28 * mm, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#1E3A5F"))
    pdf.setLineWidth(0.7)
    pdf.rect(18 * mm, 18 * mm, width - 36 * mm, height - 36 * mm, fill=0, stroke=1)

    pdf.setFillColor(colors.white)
    pdf.setFont(_FONT_BOLD, 27)
    pdf.drawCentredString(width / 2, height - 39 * mm, _visual("شهادة الوعي الأمني"))
    pdf.setFillColor(_CYAN)
    pdf.setFont(_FONT_REGULAR, 9)
    pdf.drawCentredString(width / 2, height - 48 * mm, "SECURITY AWARENESS CERTIFICATE")

    pdf.setFillColor(colors.HexColor("#CBD5E1"))
    pdf.setFont(_FONT_REGULAR, 11)
    pdf.drawCentredString(width / 2, height - 64 * mm, _visual("تُمنح هذه الشهادة إلى"))

    pdf.setFillColor(colors.white)
    pdf.setFont(_FONT_BOLD, 23)
    pdf.drawCentredString(width / 2, height - 78 * mm, _visual(employee.full_name))

    pdf.setFillColor(colors.HexColor("#CBD5E1"))
    pdf.setFont(_FONT_REGULAR, 10)
    pdf.drawCentredString(
        width / 2,
        height - 90 * mm,
        _visual(f"لإتمام شهر التوعية الأمنية {month_year}"),
    )
    pdf.setFillColor(_MUTED)
    pdf.setFont(_FONT_REGULAR, 8)
    pdf.drawCentredString(
        width / 2,
        height - 97 * mm,
        f"For completing the security awareness month {month_year}",
    )

    # Score / level boxes.
    box_y = height - 128 * mm
    box_w = 58 * mm
    box_h = 25 * mm
    left_x = width / 2 - box_w - 8 * mm
    right_x = width / 2 + 8 * mm
    for x, label_ar, value, value_color in (
        (left_x, "درجة Elo النهائية", str(score), _CYAN),
        (right_x, "مستوى الوعي", level_ar, _GREEN),
    ):
        pdf.setFillColor(colors.HexColor("#0F1E33"))
        pdf.roundRect(x, box_y, box_w, box_h, 4 * mm, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#94A3B8"))
        pdf.setFont(_FONT_REGULAR, 8)
        pdf.drawCentredString(x + box_w / 2, box_y + box_h - 7 * mm, _visual(label_ar))
        pdf.setFillColor(value_color)
        pdf.setFont(_FONT_BOLD, 20)
        pdf.drawCentredString(x + box_w / 2, box_y + 7 * mm, _visual(value))

    pdf.setFillColor(colors.HexColor("#94A3B8"))
    pdf.setFont(_FONT_REGULAR, 8)
    pdf.drawCentredString(
        width / 2,
        box_y - 9 * mm,
        _visual(
            f"البلاغات: {total_reports}   ·   النقرات: {total_clicks}   ·   "
            f"الإدخالات: {total_submissions}   ·   المستوى بالإنجليزية: {level_en}"
        ),
    )

    pdf.setStrokeColor(colors.HexColor("#1E3A5F"))
    pdf.setLineWidth(0.5)
    pdf.line(38 * mm, 37 * mm, 95 * mm, 37 * mm)
    pdf.line(width - 95 * mm, 37 * mm, width - 38 * mm, 37 * mm)
    pdf.setFillColor(colors.HexColor("#94A3B8"))
    pdf.setFont(_FONT_REGULAR, 7.5)
    pdf.drawCentredString(66 * mm, 31 * mm, _visual("مدير الأمن السيبراني"))
    pdf.drawCentredString(width - 66 * mm, 31 * mm, _visual("تاريخ الإصدار"))
    pdf.drawCentredString(
        width - 66 * mm,
        26 * mm,
        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    pdf.setFillColor(_MUTED)
    pdf.setFont(_FONT_REGULAR, 7)
    pdf.drawCentredString(
        width / 2,
        21 * mm,
        "HUMINT Shield · Verified Awareness Program",
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def build_monthly_report_pdf(
    organization_name: str,
    month_year: str,
    rows: Sequence[dict[str, Any]],
    *,
    average_elo: float | None = None,
) -> bytes:
    """Render the monthly archive report (all names/scores) as PDF bytes."""
    _register_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Monthly Elo report {month_year}",
    )

    title_style = _style(size=18, bold=True, color=_NAVY, align=TA_CENTER)
    subtitle_style = _style(size=10, color=_MUTED, align=TA_CENTER)
    cell_style = _style(size=7.2, color=_INK)
    number_style = _style(size=7.2, color=_INK, align=TA_CENTER)
    header_style = _style(size=7.6, bold=True, color=colors.white, align=TA_CENTER)

    story: list[Any] = [
        _paragraph(f"تقرير الوعي الأمني الشهري — {month_year}", title_style),
        _paragraph(organization_name, subtitle_style),
        Spacer(1, 4 * mm),
    ]
    computed_average = average_elo
    if computed_average is None and rows:
        computed_average = sum(int(row["final_elo_score"]) for row in rows) / len(rows)
    summary_text = (
        f"عدد الموظفين: {len(rows)}   ·   متوسط Elo: {computed_average:.1f}"
        if computed_average is not None
        else f"عدد الموظفين: {len(rows)}   ·   لا توجد بيانات"
    )
    story.append(_paragraph(summary_text, subtitle_style))
    story.append(Spacer(1, 4 * mm))

    headers = [
        "المستوى",
        "الإدخالات",
        "النقرات",
        "البلاغات",
        "Elo",
        "القسم",
        "البريد",
        "الموظف",
    ]
    data: list[list[Any]] = [[_paragraph(header, header_style) for header in headers]]
    for row in rows:
        name = str(row.get("employee_name") or row.get("email") or "—")
        if row.get("is_blacklisted"):
            name += " ⛔"
        data.append(
            [
                _paragraph(row.get("awareness_level_ar") or row.get("awareness_level"), cell_style),
                _paragraph(row.get("total_submissions", 0), number_style),
                _paragraph(row.get("total_clicks", 0), number_style),
                _paragraph(row.get("total_reports", 0), number_style),
                _paragraph(row.get("final_elo_score", 0), number_style),
                _paragraph(row.get("department") or "—", cell_style),
                _paragraph(row.get("email") or "—", cell_style),
                _paragraph(name, cell_style),
            ]
        )
    if not rows:
        data.append([_paragraph("لا توجد أرشيفات لهذا الشهر", cell_style)] + [""] * 7)

    table = Table(
        data,
        colWidths=[18 * mm, 16 * mm, 15 * mm, 15 * mm, 13 * mm, 26 * mm, 45 * mm, 38 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(
        _paragraph(
            "يُحتسب متوسط Elo من الأرشيف الشهري بعد تصفير الدرجة الحية إلى 1000. "
            "الموظفون المميزون بعلامة ⛔ مدرجون في قائمة الفشل المتكرر.",
            _style(size=7.5, color=_MUTED),
        )
    )

    def _footer(pdf_canvas, _doc) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setFont(_FONT_REGULAR, 7)
        pdf_canvas.setFillColor(_MUTED)
        pdf_canvas.drawCentredString(
            A4[0] / 2, 8 * mm, "HUMINT Shield · Monthly Awareness Report"
        )
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_monthly_org_report_pdf(
    organization_name: str,
    month_year: str,
    rows: Sequence[dict[str, Any]],
    *,
    average_elo: float | None = None,
) -> bytes:
    """Render the organization's monthly summary PDF.

    Unlike the full archive report this executive view answers three questions
    only: who is riskiest (bottom ten Elo), who reports the most (top ten
    reporters) and what the organization-average Elo is.

    Args:
        organization_name: Tenant name printed in the header.
        month_year: ``YYYY-MM`` month the report covers.
        rows: Archive (or live) rows for the month.
        average_elo: Pre-computed average, recomputed when omitted.

    Returns:
        The PDF document as bytes.
    """
    _register_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    title_style = _style(size=18, bold=True, color=_NAVY, align=TA_CENTER)
    subtitle_style = _style(size=10, color=_MUTED, align=TA_CENTER)
    heading_style = _style(size=11, bold=True, color=_NAVY)
    cell_style = _style(size=7.2, color=_INK)
    header_style = _style(size=7.6, bold=True, color=colors.white, align=TA_CENTER)

    computed_average = average_elo
    if computed_average is None and rows:
        computed_average = sum(int(row.get("final_elo_score") or 0) for row in rows) / len(rows)

    story: list[Any] = [
        _paragraph(f"التقرير التنفيذي الشهري — {month_year}", title_style),
        _paragraph(organization_name, subtitle_style),
        Spacer(1, 4 * mm),
    ]
    summary_text = (
        f"عدد الموظفين: {len(rows)}   ·   متوسط Elo: {computed_average:.1f}"
        if computed_average is not None
        else f"عدد الموظفين: {len(rows)}   ·   لا توجد بيانات لهذا الشهر"
    )
    story.extend([_paragraph(summary_text, subtitle_style), Spacer(1, 5 * mm)])

    def _table(
        title: str, headers: Sequence[str], data_rows: Sequence[Sequence[Any]]
    ) -> None:
        """Append a titled top-ten table."""
        story.append(_paragraph(title, heading_style))
        data: list[list[Any]] = [
            [_paragraph(header, header_style) for header in headers]
        ]
        for row in data_rows:
            data.append(
                [
                    _paragraph(value if value not in (None, "") else "—", cell_style)
                    for value in row
                ]
            )
        if len(data) == 1:
            story.append(_paragraph("لا توجد بيانات.", cell_style))
        else:
            table = Table(data, colWidths=[34 * mm, 40 * mm, 30 * mm, 26 * mm, 26 * mm])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#F8FAFC")],
                        ),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(table)
        story.append(Spacer(1, 5 * mm))

    top_risk = sorted(rows, key=lambda row: int(row.get("final_elo_score") or 0))[:10]
    top_reporters = sorted(
        rows, key=lambda row: int(row.get("total_reports") or 0), reverse=True
    )[:10]

    _table(
        "أعلى 10 مخاطر",
        ["Elo", "البلاغات", "القسم", "البريد", "الموظف"],
        [
            [
                row.get("final_elo_score"),
                row.get("total_reports", 0),
                row.get("department"),
                row.get("email"),
                row.get("employee_name"),
            ]
            for row in top_risk
        ],
    )
    _table(
        "أعلى 10 مُبلّغين",
        ["البلاغات", "Elo", "القسم", "البريد", "الموظف"],
        [
            [
                row.get("total_reports", 0),
                row.get("final_elo_score"),
                row.get("department"),
                row.get("email"),
                row.get("employee_name"),
            ]
            for row in top_reporters
        ],
    )
    story.append(
        _paragraph(
            "أعلى المخاطر مرتّبة تصاعدياً حسب Elo؛ أعلى المُبلّغين مرتّبون تنازلياً "
            "حسب عدد البلاغات. المصدر: الأرشيف الشهري غير القابل للتعديل.",
            _style(size=7.5, color=_MUTED),
        )
    )

    def _footer(pdf_canvas, _doc) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setFont(_FONT_REGULAR, 7)
        pdf_canvas.setFillColor(_MUTED)
        pdf_canvas.drawCentredString(
            A4[0] / 2, 8 * mm, "HUMINT Shield · Monthly Executive Report"
        )
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_employee_report_pdf(
    employee: HumanAsset,
    organization_name: str,
    *,
    summary: dict[str, Any] | None = None,
    campaigns: Sequence[dict[str, Any]] | None = None,
    events: Sequence[dict[str, Any]] | None = None,
    submissions: Sequence[dict[str, Any]] | None = None,
    certificates: Sequence[dict[str, Any]] | None = None,
) -> bytes:
    """Render one employee's complete intelligence profile as PDF bytes.

    The report is the printable counterpart of the Employee Intelligence Hub:
    profile and current Elo, the behavioural summary, one row per campaign, the
    latest ledger events, every captured submission (already masked by the
    caller) and the monthly certificates on record.

    Args:
        employee: The employee the report is about.
        organization_name: Tenant name printed in the header.
        summary: Aggregate counters from the dossier.
        campaigns: Per-campaign records.
        events: Most recent ledger events.
        submissions: Captured form submissions (values already masked).
        certificates: Monthly archive rows.

    Returns:
        The PDF document as bytes.
    """
    _register_fonts()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    score = int(employee.elo_score or INITIAL_ELO)
    title_style = _style(size=18, bold=True, color=_NAVY, align=TA_CENTER)
    subtitle_style = _style(size=10, color=_MUTED, align=TA_CENTER)
    heading_style = _style(size=11, bold=True, color=_NAVY)
    body_style = _style(size=8, color=_INK)
    cell_style = _style(size=7.2, color=_INK)
    number_style = _style(size=7.2, color=_INK, align=TA_CENTER)
    header_style = _style(size=7.4, bold=True, color=colors.white, align=TA_CENTER)

    story: list[Any] = [
        _paragraph("تقرير الموظف الأمني الشامل", title_style),
        _paragraph(employee.full_name, subtitle_style),
        _paragraph(organization_name, subtitle_style),
        Spacer(1, 5 * mm),
    ]

    facts = [
        ("البريد الإلكتروني", employee.email or "—"),
        ("القسم", employee.department or "—"),
        ("المسمى الوظيفي", employee.job_title or "—"),
        ("درجة Elo", str(score)),
        ("مستوى الوعي", awareness_level_ar(score)),
        ("التصنيف السلوكي", employee.behavioral_category or "—"),
    ]
    fact_table = Table(
        [
            [
                _paragraph(label, header_style),
                _paragraph(value, cell_style),
                _paragraph(other_label, header_style),
                _paragraph(other_value, cell_style),
            ]
            for (label, value), (other_label, other_value) in zip(
                facts[0::2], facts[1::2], strict=False
            )
        ],
        colWidths=[32 * mm, 53 * mm, 32 * mm, 53 * mm],
    )
    fact_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), _NAVY),
                ("BACKGROUND", (2, 0), (2, -1), _NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([fact_table, Spacer(1, 5 * mm)])

    if summary:
        story.append(_paragraph("الملخص السلوكي", heading_style))
        summary_text = (
            f"الحملات: {summary.get('campaigns', 0)}   ·   "
            f"أُرسلت: {summary.get('emails_sent', 0)}   ·   "
            f"فُتحت: {summary.get('opened', 0)}   ·   "
            f"نُقرت: {summary.get('clicked', 0)}   ·   "
            f"إدخالات: {summary.get('submitted', 0)}   ·   "
            f"بلاغات: {summary.get('reported', 0)}   ·   "
            f"أكمل التدريب: {summary.get('completed', 0)}"
        )
        story.extend([_paragraph(summary_text, body_style), Spacer(1, 4 * mm)])

    def _section(
        title: str,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        widths: Sequence[float],
        empty_text: str,
    ) -> None:
        """Append a titled table section to the story."""
        story.append(_paragraph(title, heading_style))
        data: list[list[Any]] = [
            [_paragraph(header, header_style) for header in headers]
        ]
        for row in rows:
            data.append(
                [
                    _paragraph(
                        "—" if value in (None, "") else str(value), cell_style
                    )
                    for value in row
                ]
            )
        if not rows:
            story.append(_paragraph(empty_text, body_style))
        else:
            table = Table(data, colWidths=list(widths), repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#F8FAFC")],
                        ),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(table)
        story.append(Spacer(1, 4 * mm))

    _section(
        "الحملات",
        ["الحالة", "الإدخالات", "النقرات", "القناة", "التاريخ", "الحملة"],
        [
            [
                row.get("status"),
                row.get("submission_count", 0),
                row.get("click_count", 0),
                row.get("channel"),
                str(row.get("sent_at") or "")[:10],
                row.get("campaign_name"),
            ]
            for row in (campaigns or [])
        ],
        [22 * mm, 18 * mm, 16 * mm, 20 * mm, 24 * mm, 70 * mm],
        "لا توجد حملات مسجلة.",
    )

    _section(
        "أحدث الأحداث",
        ["الحدث", "الحدث", "IP", "الوقت"],
        [
            [
                event.get("event_type"),
                event.get("campaign_name"),
                event.get("ip_address"),
                str(event.get("occurred_at") or "")[:19],
            ]
            for event in (events or [])[-25:]
        ],
        [40 * mm, 55 * mm, 40 * mm, 35 * mm],
        "لا توجد أحداث مسجلة.",
    )

    _section(
        "البيانات المدخلة (كلمات المرور مقنّعة)",
        ["القيم", "طول كلمة المرور", "IP", "الوقت"],
        [
            [
                " · ".join(f"{key}={value}" for key, value in (row.get("values") or {}).items()),
                row.get("password_length"),
                row.get("ip_address"),
                str(row.get("occurred_at") or "")[:19],
            ]
            for row in (submissions or [])[-25:]
        ],
        [60 * mm, 20 * mm, 40 * mm, 35 * mm],
        "لا توجد بيانات مدخلة.",
    )

    _section(
        "الشهادات",
        ["المستوى", "الإدخالات", "النقرات", "البلاغات", "Elo", "الشهر"],
        [
            [
                awareness_level_ar(int(row.get("final_elo_score") or 0)),
                row.get("total_submissions", 0),
                row.get("total_clicks", 0),
                row.get("total_reports", 0),
                row.get("final_elo_score"),
                row.get("month_year"),
            ]
            for row in (certificates or [])
        ],
        [40 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 30 * mm],
        "لا توجد شهادات شهرية بعد.",
    )

    def _footer(pdf_canvas, _doc) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setFont(_FONT_REGULAR, 7)
        pdf_canvas.setFillColor(_MUTED)
        pdf_canvas.drawCentredString(
            A4[0] / 2, 8 * mm, "HUMINT Shield · Employee Intelligence Report"
        )
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def build_certificates_zip(
    month_year: str,
    rows: Sequence[dict[str, Any]],
) -> bytes:
    """Bundle every archived employee certificate for a month into a ZIP."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            employee = row.get("employee")
            if employee is None:
                continue
            pdf_bytes = build_certificate_pdf(
                employee,
                month_year,
                int(row.get("final_elo_score") or INITIAL_ELO),
                int(row.get("total_reports") or 0),
                int(row.get("total_clicks") or 0),
                int(row.get("total_submissions") or 0),
            )
            filename = (
                f"certificate-{_safe_filename(employee.email)}-{month_year}.pdf"
            )
            archive.writestr(filename, pdf_bytes)
    return buffer.getvalue()


__all__ = [
    "apply_elo_action",
    "archive_monthly_scores",
    "campaign_difficulty",
    "build_certificate_pdf",
    "build_certificates_zip",
    "build_monthly_report_pdf",
    "current_month_year",
    "get_send_blockers",
    "is_last_day_of_month",
    "month_bounds",
    "tracking_difficulty",
    "validate_month",
]
