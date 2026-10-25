"""Executive PDF report for one campaign.

The report is generated with ReportLab and is fully Arabic/RTL capable: Amiri
is bundled under ``app/assets/fonts`` and every Arabic string is shaped with
``arabic-reshaper`` + ``python-bidi`` before it reaches ReportLab.

The report is intentionally self-contained: one PDF with the campaign summary,
open/click pie charts, a risky-department bar chart, and the five employees with
the lowest Elo (the highest simulated risk).
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, Organization
from app.services.elo_engine import threat_label

logger = get_logger(__name__)

_ASSET_DIR = __file__.replace("\\", "/").rsplit("/", 2)[0] + "/assets/fonts"
_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONTS_READY = False
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

#: Page geometry.
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN = 16 * mm
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN

#: Palette.
_INK = colors.HexColor("#0B1220")
_SLATE = colors.HexColor("#475569")
_MUTED = colors.HexColor("#64748B")
_LINE = colors.HexColor("#E2E8F0")
_CYAN = colors.HexColor("#0891B2")
_BLUE = colors.HexColor("#2563EB")
_RED = colors.HexColor("#DC2626")
_AMBER = colors.HexColor("#D97706")
_GREEN = colors.HexColor("#059669")


def _register_fonts() -> None:
    """Register the bundled Arabic font, falling back to a system font."""
    global _FONT_REGULAR, _FONT_BOLD, _FONTS_READY
    if _FONTS_READY:
        return

    candidates = [
        (
            f"{_ASSET_DIR}/Amiri-Regular.ttf",
            f"{_ASSET_DIR}/Amiri-Bold.ttf",
            "Amiri",
            "Amiri-Bold",
        ),
        (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "ReportArabic",
            "ReportArabic-Bold",
        ),
    ]
    for regular_path, bold_path, regular_name, bold_name in candidates:
        try:
            with open(regular_path, "rb"):
                pass
            with open(bold_path, "rb"):
                pass
        except OSError:
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular_name, regular_path))
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            pdfmetrics.registerFontFamily(
                regular_name,
                normal=regular_name,
                bold=bold_name,
                italic=regular_name,
                boldItalic=bold_name,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the next candidate
            logger.warning("pdf_font_registration_failed", path=regular_path, error=str(exc))
            continue
        _FONT_REGULAR = regular_name
        _FONT_BOLD = bold_name
        _FONTS_READY = True
        return

    logger.warning("pdf_arabic_font_missing", asset_dir=_ASSET_DIR)
    _FONT_REGULAR = "Helvetica"
    _FONT_BOLD = "Helvetica-Bold"
    _FONTS_READY = True


def _visual(value: Any) -> str:
    """Return a shaped visual-order string for ReportLab drawing primitives."""
    text = "" if value is None else str(value)
    if _ARABIC_RE.search(text):
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:  # pragma: no cover - shaping is best effort
            return text
    return text


def _paragraph_text(value: Any) -> str:
    """Return XML-escaped, shaped text for a ReportLab ``Paragraph``."""
    return escape(_visual(value))


def _style(
    *,
    font: str | None = None,
    size: float = 9,
    leading: float | None = None,
    color: colors.Color | None = None,
    align: int = TA_RIGHT,
    space_after: float = 0,
) -> ParagraphStyle:
    """Build a consistently configured RTL paragraph style."""
    return ParagraphStyle(
        name=f"rtl-{size}-{font or _FONT_REGULAR}-{id(color)}",
        fontName=font or _FONT_REGULAR,
        fontSize=size,
        leading=leading or size * 1.55,
        textColor=color or _INK,
        alignment=align,
        spaceAfter=space_after,
    )


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    """Create a Paragraph from an arbitrary value using shaped text."""
    return Paragraph(_paragraph_text(value), style)


def _fmt_dt(value: datetime | None) -> str:
    """Format a timestamp for the report in UTC."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pct(value: int, total: int) -> str:
    """Return a percentage label without dividing by zero."""
    if not total:
        return "0%"
    return f"{value / total * 100:.1f}%"


def _drawing_title(drawing: Drawing, title: str, width: float) -> None:
    """Draw a right-aligned title inside a chart drawing."""
    text = _visual(title)
    text_width = pdfmetrics.stringWidth(text, _FONT_BOLD, 9)
    drawing.add(
        String(
            width - 8 - text_width,
            drawing.height - 18,
            text,
            fontName=_FONT_BOLD,
            fontSize=9,
            fillColor=_INK,
        )
    )


def _pie_drawing(
    title: str,
    opened: int,
    total: int,
    *,
    color: colors.Color,
    opened_label: str,
    closed_label: str,
) -> Drawing:
    """Build one open/click pie chart as a ReportLab drawing."""
    width, height = 245, 175
    drawing = Drawing(width, height)
    _drawing_title(drawing, title, width)
    if total <= 0:
        drawing.add(
            String(
                70,
                75,
                _visual("لا توجد بيانات"),
                fontName=_FONT_REGULAR,
                fontSize=10,
                fillColor=_MUTED,
            )
        )
        return drawing

    pie_width = 135
    pie_height = 115
    pie = Pie()
    pie.x = 12
    pie.y = 12
    pie.width = pie_width
    pie.height = pie_height
    pie.data = [max(0, opened), max(0, total - opened)]
    pie.labels = [_visual(opened_label), _visual(closed_label)]
    pie.startAngle = 90
    pie.direction = "clockwise"
    pie.simpleLabels = 1
    pie.sideLabels = 0
    pie.slices[0].fillColor = color
    pie.slices[1].fillColor = colors.HexColor("#E2E8F0")
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    pie.slices.fontName = _FONT_REGULAR
    pie.slices.fontSize = 7
    pie.slices.fontColor = _INK
    drawing.add(pie)
    summary = f"{opened}/{total} · {_pct(opened, total)}"
    drawing.add(
        String(
            width - 8 - pdfmetrics.stringWidth(summary, _FONT_REGULAR, 8),
            8,
            summary,
            fontName=_FONT_REGULAR,
            fontSize=8,
            fillColor=_SLATE,
        )
    )
    return drawing


def _bar_drawing(
    title: str,
    departments: list[tuple[str, int, int, int]],
    *,
    width: float,
) -> Drawing:
    """Build a horizontal risky-department bar chart.

    Args:
        title: Chart title.
        departments: Tuples of ``(name, risk_score, clicked, submitted)``.
        width: Drawing width in points.
    """
    row_height = 23
    height = max(120, 42 + row_height * max(1, len(departments)))
    drawing = Drawing(width, height)
    _drawing_title(drawing, title, width)
    if not departments:
        drawing.add(
            String(
                20,
                height / 2,
                _visual("لا توجد بيانات"),
                fontName=_FONT_REGULAR,
                fontSize=10,
                fillColor=_MUTED,
            )
        )
        return drawing

    max_value = max((item[1] for item in departments), default=0) or 1
    label_area = 126
    bar_left = 38
    bar_right = width - label_area
    bar_width = max(10, bar_right - bar_left)
    top = height - 34
    for index, (name, risk, clicked, submitted) in enumerate(departments):
        y = top - index * row_height
        drawing.add(
            Rect(
                bar_left,
                y,
                bar_width,
                13,
                fillColor=colors.HexColor("#F1F5F9"),
                strokeColor=None,
            )
        )
        fill_width = max(0.0, min(bar_width, bar_width * risk / max_value))
        if fill_width:
            drawing.add(
                Rect(
                    bar_right - fill_width,
                    y,
                    fill_width,
                    13,
                    fillColor=_RED if risk >= 4 else _AMBER,
                    strokeColor=None,
                )
            )
        label = _visual(name)[:28]
        drawing.add(
            String(
                bar_right + 8,
                y + 3,
                label,
                fontName=_FONT_REGULAR,
                fontSize=7.5,
                fillColor=_INK,
            )
        )
        detail = f"{risk} · {clicked}/{submitted}"
        drawing.add(
            String(
                4,
                y + 3,
                detail,
                fontName=_FONT_REGULAR,
                fontSize=6.5,
                fillColor=_SLATE,
            )
        )
    drawing.add(
        String(
            width - 8 - pdfmetrics.stringWidth(_visual("الخطر = نقرات×2 + بيانات×3"), _FONT_REGULAR, 6.5),
            6,
            _visual("الخطر = نقرات×2 + بيانات×3"),
            fontName=_FONT_REGULAR,
            fontSize=6.5,
            fillColor=_MUTED,
        )
    )
    return drawing


class ExecutiveReportService:
    """Collect campaign data and render the executive PDF."""

    async def generate(
        self,
        campaign: EmailCampaign,
        organization: Organization,
        db: AsyncSession,
    ) -> bytes:
        """Return a complete PDF for ``campaign`` as bytes."""
        _register_fonts()
        rows = (
            await db.execute(
                select(EmailTracking, HumanAsset)
                .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
                .where(EmailTracking.campaign_id == campaign.id)
                .order_by(EmailTracking.created_at.asc())
            )
        ).all()

        sent_from_rows = sum(1 for tracking, _ in rows if tracking.sent_at is not None)
        sent = max(int(campaign.sent_count or 0), sent_from_rows)
        total = max(int(campaign.total_targets or 0), len(rows))
        opened = sum(1 for tracking, _ in rows if tracking.opened_at is not None)
        clicked = sum(1 for tracking, _ in rows if tracking.clicked_at is not None)
        submitted = sum(1 for tracking, _ in rows if tracking.submitted_at is not None)
        # Keep the chart denominators sane even for manually-created tracking
        # rows whose campaign counters were never incremented.
        sent = max(sent, opened, clicked, submitted)
        completed = sum(1 for tracking, _ in rows if tracking.completed_at is not None)
        reported = sum(1 for tracking, _ in rows if tracking.is_reported_safe)

        dept_map: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "clicked": 0, "submitted": 0}
        )
        employee_rows: list[dict[str, Any]] = []
        for tracking, employee in rows:
            department = (employee.department or "").strip() or "غير محدد"
            item = dept_map[department]
            item["total"] += 1
            item["clicked"] += 1 if tracking.clicked_at else 0
            item["submitted"] += 1 if tracking.submitted_at else 0
            elo = int(employee.elo_score or 1000)
            employee_rows.append(
                {
                    "name": employee.full_name or employee.email,
                    "department": department,
                    "elo": elo,
                    "threat": threat_label(elo, arabic=True),
                    "clicked": tracking.click_count or 0,
                    "submitted": tracking.submission_count or 0,
                    "reported": bool(tracking.is_reported_safe),
                }
            )

        departments = sorted(
            (
                (
                    name,
                    values["clicked"] * 2 + values["submitted"] * 3,
                    values["clicked"],
                    values["submitted"],
                )
                for name, values in dept_map.items()
            ),
            key=lambda item: (item[1], item[2], item[3], item[0]),
            reverse=True,
        )[:6]
        top_employees = sorted(
            employee_rows,
            key=lambda row: (
                row["elo"],
                -row["submitted"],
                -row["clicked"],
                row["name"],
            ),
        )[:5]

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=_MARGIN,
            leftMargin=_MARGIN,
            topMargin=14 * mm,
            bottomMargin=18 * mm,
            title="HUMINT Shield — Executive Report",
            author="HUMINT Shield",
            subject=campaign.name,
        )
        story = self._build_story(
            campaign=campaign,
            organization=organization,
            total=total,
            sent=sent,
            opened=opened,
            clicked=clicked,
            submitted=submitted,
            completed=completed,
            reported=reported,
            departments=departments,
            top_employees=top_employees,
        )
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return buffer.getvalue()

    def _build_story(
        self,
        *,
        campaign: EmailCampaign,
        organization: Organization,
        total: int,
        sent: int,
        opened: int,
        clicked: int,
        submitted: int,
        completed: int,
        reported: int,
        departments: list[tuple[str, int, int, int]],
        top_employees: list[dict[str, Any]],
    ) -> list[Any]:
        """Build the flowable story for the report."""
        title_style = _style(font=_FONT_BOLD, size=20, leading=26, color=colors.white)
        section_style = _style(font=_FONT_BOLD, size=12, leading=17, color=_INK, space_after=5)
        body_style = _style(size=9, leading=14, color=_SLATE)
        small_style = _style(size=7, leading=11, color=_MUTED)

        banner_text = (
            f'<font size="20">{_paragraph_text("تقرير تنفيذي")}</font><br/>'
            f'<font size="8" color="#94A3B8">{_paragraph_text("HUMINT Shield · تحليل حملة توعية أمنية")}</font>'
        )
        banner = Table(
            [[Paragraph(banner_text, title_style)]],
            colWidths=[_CONTENT_WIDTH],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _INK),
                    ("LEFTPADDING", (0, 0), (-1, -1), 14),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                    ("TOPPADDING", (0, 0), (-1, -1), 13),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
                ]
            ),
        )
        story: list[Any] = [
            banner,
            Spacer(1, 10),
            _p(f"الحملة: {campaign.name}", _style(font=_FONT_BOLD, size=14, leading=20)),
            _p(
                f"المؤسسة: {organization.name} · القطاع: {organization.industry or 'غير محدد'}",
                body_style,
            ),
            _p(
                f"الفترة: {_fmt_dt(campaign.created_at)} — {_fmt_dt(campaign.completed_at)}",
                small_style,
            ),
            Spacer(1, 8),
            self._kpi_table(
                total=total,
                sent=sent,
                opened=opened,
                clicked=clicked,
                submitted=submitted,
                completed=completed,
                reported=reported,
            ),
            Spacer(1, 12),
            _p("نظرة عامة على التفاعل", section_style),
            Table(
                [
                    [
                        _pie_drawing(
                            "فتح الرسالة",
                            opened,
                            sent,
                            color=_CYAN,
                            opened_label="فُتح",
                            closed_label="لم يُفتح",
                        ),
                        _pie_drawing(
                            "النقر على الرابط",
                            clicked,
                            sent,
                            color=_BLUE,
                            opened_label="نقر",
                            closed_label="لم ينقر",
                        ),
                    ]
                ],
                colWidths=[_CONTENT_WIDTH / 2, _CONTENT_WIDTH / 2],
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                ),
            ),
            Spacer(1, 12),
            _p("الأقسام الأكثر خطراً", section_style),
            _bar_drawing("درجة الخطر حسب القسم", departments, width=_CONTENT_WIDTH),
            Spacer(1, 10),
            KeepTogether(
                [
                    _p("أعلى 5 موظفين خطراً", section_style),
                    self._top_employees_table(top_employees),
                ]
            ),
            Spacer(1, 10),
            _p(
                "ملاحظة: درجة Elo تبدأ من 1000. النقر على رابط محاكاة يخصم 32 نقطة، "
                "والإبلاغ عن الرسالة يضيف 32 نقطة. المستوى المنخفض يعني وعياً أعلى.",
                small_style,
            ),
            _p(
                "هذا التقرير سري ومخصص للاستخدام الداخلي. البيانات مستخرجة من سجلات الحملة "
                "الفعلية، ولا تتضمن كلمات المرور أو القيم الحساسة.",
                small_style,
            ),
        ]
        return story

    def _kpi_table(
        self,
        *,
        total: int,
        sent: int,
        opened: int,
        clicked: int,
        submitted: int,
        completed: int,
        reported: int,
    ) -> Table:
        """Build the six-cell KPI strip in RTL order."""
        labels = [
            "المستهدفون",
            "تم الإرسال",
            "فتحوا",
            "نقروا",
            "قدّموا بيانات",
            "أكملوا التدريب",
        ]
        values = [total, sent, opened, clicked, submitted, completed]
        # ReportLab lays columns left-to-right; reverse so the first logical
        # label appears at the right edge, where an Arabic reader starts.
        labels = list(reversed(labels))
        values = list(reversed(values))
        label_style = _style(font=_FONT_REGULAR, size=7, leading=10, color=_SLATE)
        value_style = _style(font=_FONT_BOLD, size=13, leading=18, color=_INK)
        data = [
            [_p(label, label_style) for label in labels],
            [_p(value, value_style) for value in values],
        ]
        table = Table(
            data,
            colWidths=[_CONTENT_WIDTH / 6] * 6,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                    ("BACKGROUND", (0, 1), (-1, 1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.5, _LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, _LINE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
        return table

    def _top_employees_table(self, rows: list[dict[str, Any]]) -> Table:
        """Build the top-five risk table in RTL column order."""
        headers = ["الموظف", "القسم", "Elo", "مستوى الخطر", "النقرات", "البيانات المقدمة"]
        data: list[list[Any]] = [
            [_p(header, _style(font=_FONT_BOLD, size=7.5, leading=10, color=colors.white))
             for header in reversed(headers)]
        ]
        if not rows:
            data.append([_p("لا توجد بيانات", _style(size=8, leading=12, color=_MUTED))] + [""] * 5)
        else:
            for row in rows:
                logical = [
                    row["name"],
                    row["department"],
                    str(row["elo"]),
                    row["threat"],
                    str(row["clicked"]),
                    str(row["submitted"]),
                ]
                data.append(
                    [
                        _p(value, _style(size=7.5, leading=10, color=_INK))
                        for value in reversed(logical)
                    ]
                )
        table = Table(
            data,
            colWidths=[
                _CONTENT_WIDTH * 0.24,
                _CONTENT_WIDTH * 0.21,
                _CONTENT_WIDTH * 0.10,
                _CONTENT_WIDTH * 0.17,
                _CONTENT_WIDTH * 0.13,
                _CONTENT_WIDTH * 0.15,
            ],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _INK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("BOX", (0, 0), (-1, -1), 0.5, _LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, _LINE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
        if not rows:
            table.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1))]))
        return table

    @staticmethod
    def _footer(canvas, doc) -> None:  # noqa: ANN001 - ReportLab callback
        """Draw the confidentiality footer and page number."""
        canvas.saveState()
        canvas.setStrokeColor(_LINE)
        canvas.setLineWidth(0.5)
        canvas.line(_MARGIN, 13 * mm, _PAGE_WIDTH - _MARGIN, 13 * mm)
        canvas.setFont(_FONT_REGULAR, 7)
        canvas.setFillColor(_MUTED)
        footer = _visual("سري · HUMINT Shield · تقرير تنفيذي")
        canvas.drawRightString(
            _PAGE_WIDTH - _MARGIN,
            8 * mm,
            footer,
        )
        canvas.drawString(_MARGIN, 8 * mm, f"{doc.page}")
        canvas.restoreState()


__all__ = ["ExecutiveReportService"]
