"""Safe USB-drop awareness documents.

This module builds **inert** deliverables for an authorized physical USB-drop
exercise:

* a standard PDF salary statement with a QR tracking link, and
* a standalone HTML salary document that immediately calls the USB tracking
  endpoint with ``fetch`` and then shows the required red warning.

Neither deliverable contains an executable, an auto-run action, a macro, a
credential form, or any code that reads local files.  The HTML uses only a
single same-purpose network request plus benign DOM updates.

Every document carries a unique tracking link so an open can be attributed to
one employee without embedding any personal data in the file itself.
"""
from __future__ import annotations

import html
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.quishing_service import (
    _draw_initial_mark,
    _draw_logo,
    _draw_rtl_lines,
    _fonts,
    _text,
    _visual,
    _wrap,
    generate_qr_png,
)

#: The fixed awareness message required by the exercise.  It is intentionally
#: not configurable: an operator must not be able to remove the teachable
#: moment from the document.
USB_WARNING = (
    "لقد قمت بتوصيل فلاشة مجهولة. هذا كان اختباراً أمنياً. "
    "في الهجوم الحقيقي، كان بإمكان هذا الملف تدمير جهازك."
)

#: Exact warning required for the HTML USB artefact.  The sentence is kept in
#: one literal so tests and operators can verify it byte-for-byte.
USB_HTML_WARNING = (
    "لقد قمت بتوصيل فلاشة مجهولة. تم اختراق جهازك الآن. "
    "هذا كان اختباراً تدريبياً."
)

#: Default downloaded/printed file names.  The browser receives them through an
#: RFC 5987 ``filename*`` header so the Arabic names survive the download.
DEFAULT_DOCUMENT_NAME = "راتب_الشهر_القادم.pdf"
HTML_DOCUMENT_NAME = "الرواتب_السرية.html"
DEFAULT_MONTH_LABEL = "الشهر القادم"

#: Values the old UI wrote into every USB campaign.  They are treated as "no
#: override" so the campaign template decides the file name.
_LEGACY_DEFAULT_NAMES = (
    DEFAULT_DOCUMENT_NAME,
    HTML_DOCUMENT_NAME,
    "راتب_الشهر_القادم.html",
    "الرواتب_السرية.pdf",
)

_ARABIC_MONTHS = (
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
)

# A salary statement should look like a document, not like the dark product UI.
_PAPER = colors.HexColor("#F7F5EF")
_PAPER_ALT = colors.HexColor("#EEF2F7")
_INK = colors.HexColor("#0B1220")
_INK_SOFT = colors.HexColor("#24344D")
_MUTED = colors.HexColor("#64748B")
_LINE = colors.HexColor("#CBD5E1")
_WHITE = colors.HexColor("#FFFFFF")
_RED = colors.HexColor("#B91C1C")
_RED_BG = colors.HexColor("#FEF2F2")
_RED_LINE = colors.HexColor("#FCA5A5")
_GREEN = colors.HexColor("#047857")
_AMBER = colors.HexColor("#B45309")
_ACCENT = colors.HexColor("#0E7490")


@dataclass(slots=True)
class USBDropRecipient:
    """One USB-document recipient and its unique tracking link."""

    name: str
    email: str
    tracking_uuid: str
    tracking_url: str
    department: str = ""


@dataclass(slots=True)
class USBDropCopy:
    """Resolved, operator-visible document metadata."""

    document_name: str
    month_label: str
    #: Name of the reportable HTML document.  It follows the campaign's chosen
    #: template so an "urgent password change" campaign drops a password file,
    #: not a salary statement.
    html_document_name: str = HTML_DOCUMENT_NAME


#: Template keyword -> document title.  The dropped file must match the story the
#: campaign tells; the first matching rule wins.
_TEMPLATE_TITLE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("password", "passwd", "reset", "كلمة المرور", "كلمه المرور", "إعادة تعيين"), "تحديث_كلمة_المرور"),
    (("mfa", "otp", "verification", "verify", "تحقق", "رمز"), "رمز_التحقق_الجديد"),
    (("invoice", "payment", "billing", "فاتورة", "دفعة", "مستحقات"), "فاتورة_مستحقة"),
    (("bonus", "reward", "مكافأة", "مكافاه"), "مكافأة_الأداء"),
    (("salary", "payroll", "رواتب", "راتب"), "كشف_الراتب"),
    (("vpn", "network", "firewall", "شبكة", "الجدار الناري"), "تحديث_إعدادات_الشبكة"),
    (("leave", "policy", "hr ", "سياسة", "إجازة", "موارد بشرية"), "تعميم_الموارد_البشرية"),
    (("security", "alert", "phish", "أمن", "امن", "تنبيه"), "تنبيه_أمني"),
    (("update", "upgrade", "patch", "تحديث", "ترقية"), "تحديث_النظام"),
    (("covid", "health", "صحة"), "تعميم_صحي"),
)


def template_document_title(
    template_name: str | None, template_subject: str | None = None
) -> str | None:
    """Return the document title implied by the campaign's template.

    Args:
        template_name: ``EmailTemplate.name`` of the campaign template.
        template_subject: ``EmailTemplate.subject``, used as a second signal.

    Returns:
        An Arabic file stem, or ``None`` when no rule matches.
    """
    haystack = f"{_text(template_name)} {_text(template_subject)}".lower()
    if not haystack.strip():
        return None
    for needles, title in _TEMPLATE_TITLE_RULES:
        if any(needle in haystack for needle in needles):
            return title
    return None


def _next_month_label(now: datetime | None = None) -> str:
    """Return a friendly Arabic label for the month after ``now``."""
    current = now or datetime.now(timezone.utc)
    year = current.year + (1 if current.month == 12 else 0)
    month = current.month % 12 + 1
    return f"{_ARABIC_MONTHS[month - 1]} {year}"


def safe_document_name(value: Any) -> str:
    """Return a header-safe ``.pdf`` document name.

    The value is used in ``Content-Disposition``, so path separators, control
    characters and quotes are removed.  It is not used as a filesystem path.
    """
    name = _text(value) or DEFAULT_DOCUMENT_NAME
    name = name.replace("\\", "-").replace("/", "-").replace('"', "'")
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    if not name:
        name = DEFAULT_DOCUMENT_NAME
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name[:120]


def resolve_usb_copy(
    channel_config: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    template_name: str | None = None,
    template_subject: str | None = None,
) -> USBDropCopy:
    """Resolve document metadata from the config and the campaign template.

    An explicit ``document_name`` set by the operator always wins.  Otherwise the
    file names follow the selected template (“Urgent Password Change” produces
    ``تحديث_كلمة_المرور``), so a drop never claims to be a salary statement when
    the campaign tells a different story.  With no template at all the historical
    salary defaults are kept.
    """
    config = dict(channel_config or {})
    raw = config.get("usb")
    usb = dict(raw) if isinstance(raw, Mapping) else {}
    title = template_document_title(template_name, template_subject)

    explicit_pdf = _text(usb.get("document_name"))
    # Older campaigns stored the hard-coded salary name in their channel config.
    # That was a default, not an operator decision, so it must not block the
    # template rule — otherwise every legacy USB campaign keeps dropping a salary
    # statement no matter which template was chosen.
    if explicit_pdf.strip() in _LEGACY_DEFAULT_NAMES:
        explicit_pdf = ""
    if explicit_pdf:
        document_name = safe_document_name(explicit_pdf)
    elif title:
        document_name = safe_document_name(f"{title}.pdf")
    else:
        document_name = DEFAULT_DOCUMENT_NAME

    explicit_html = _text(usb.get("html_document_name")) or explicit_pdf
    if explicit_html.strip() in _LEGACY_DEFAULT_NAMES:
        explicit_html = ""
    if explicit_html.lower().endswith(".pdf"):
        explicit_html = explicit_html[:-4]
    if explicit_html:
        html_document_name = safe_html_name(explicit_html)
    elif title:
        html_document_name = safe_html_name(f"{title}.html")
    else:
        html_document_name = HTML_DOCUMENT_NAME

    month_label = _text(usb.get("month_label")) or _next_month_label(now)
    return USBDropCopy(
        document_name=document_name,
        month_label=month_label[:80],
        html_document_name=html_document_name,
    )


def _money(value: int) -> str:
    """Format a fictional salary amount in Latin digits for the amount column."""
    return f"{value:,}"


def _draw_header(
    pdf: canvas.Canvas,
    *,
    organization: Any,
    copy: USBDropCopy,
    font_regular: str,
    font_bold: str,
) -> None:
    """Draw the branded salary-statement header."""
    width, height = A4
    company = _text(getattr(organization, "name", None)) or "Our Company"
    primary = _text(getattr(organization, "brand_primary_color", None)) or "#0E7490"
    try:
        accent = colors.HexColor(primary)
    except Exception:  # pragma: no cover - invalid legacy colour
        accent = _ACCENT

    # Deep navy masthead.
    pdf.setFillColor(_INK)
    pdf.rect(0, height - 96, width, 96, fill=1, stroke=0)
    pdf.setFillColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.35))
    pdf.rect(0, height - 100, width, 4, fill=1, stroke=0)

    logo = getattr(organization, "brand_logo_data", None)
    if not _draw_logo(
        pdf,
        logo,
        x=width - 48 - 56,
        y=height - 76,
        max_width=56,
        max_height=44,
    ):
        _draw_initial_mark(pdf, company, x=width - 48 - 44, y=height - 78, size=44)

    pdf.setFillColor(_WHITE)
    pdf.setFont(font_bold, 15)
    pdf.drawRightString(width - 116, height - 50, _visual(company))
    pdf.setFillColor(colors.HexColor("#94A3B8"))
    pdf.setFont(font_regular, 8)
    pdf.drawRightString(width - 116, height - 66, _visual("إدارة الرواتب — مستند سري"))

    # Simulation badge.
    pdf.setFillColor(colors.Color(_AMBER.red, _AMBER.green, _AMBER.blue, alpha=0.18))
    pdf.roundRect(48, height - 72, 142, 24, 12, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#FCD34D"))
    pdf.setFont(font_bold, 7.5)
    pdf.drawCentredString(119, height - 64, _visual("محاكاة توعية — ليست راتباً"))

    # Document title and period.
    pdf.setFillColor(_INK)
    pdf.setFont(font_bold, 24)
    pdf.drawRightString(width - 48, height - 142, _visual("كشف راتب"))
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 9.5)
    pdf.drawRightString(
        width - 48,
        height - 162,
        _visual(f"فترة الكشف: {copy.month_label}"),
    )
    pdf.setFillColor(_RED)
    pdf.setFont(font_bold, 8.5)
    pdf.drawString(48, height - 142, "CONFIDENTIAL")
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 7.5)
    pdf.drawString(48, height - 156, _visual("بيانات توضيحية — محاكاة"))


def _draw_employee_panel(
    pdf: canvas.Canvas,
    *,
    recipient: USBDropRecipient,
    copy: USBDropCopy,
    font_regular: str,
    font_bold: str,
) -> None:
    """Draw the recipient identity strip."""
    width, height = A4
    top = height - 236
    height_panel = 58
    pdf.setFillColor(_WHITE)
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.8)
    pdf.roundRect(48, top, width - 96, height_panel, 8, fill=1, stroke=1)

    name = (_text(recipient.name) or _text(recipient.email) or "زميلنا العزيز")[:52]
    department = (_text(recipient.department) or "—")[:40]
    pdf.setFillColor(_INK)
    pdf.setFont(font_bold, 11)
    pdf.drawRightString(width - 66, top + 34, _visual(f"الموظف: {name}"))
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 8.5)
    pdf.drawRightString(width - 66, top + 16, _visual(f"القسم: {department}"))

    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 8)
    pdf.drawRightString(300, top + 34, _visual(f"فترة الكشف: {copy.month_label}"))
    pdf.setFont(font_regular, 7.2)
    pdf.drawString(66, top + 16, f"Simulation ID: {recipient.tracking_uuid[:8]}")


def _draw_salary_table(
    pdf: canvas.Canvas,
    *,
    font_regular: str,
    font_bold: str,
) -> None:
    """Draw a realistic but entirely fictional salary breakdown."""
    width, _ = A4
    left = 48
    right = width - 48
    table_top = 590
    header_height = 22
    row_height = 24
    rows = [
        ("الراتب الأساسي", 8500),
        ("بدل السكن", 2500),
        ("بدل النقل", 800),
        ("بدلات أخرى", 400),
        ("استقطاعات (تأمينات)", -450),
        ("صافي الراتب", 11750),
    ]

    pdf.setFillColor(_INK_SOFT)
    pdf.roundRect(left, table_top - header_height, right - left, header_height, 5, fill=1, stroke=0)
    pdf.setFillColor(_WHITE)
    pdf.setFont(font_bold, 8.5)
    pdf.drawRightString(right - 12, table_top - 15, _visual("البند"))
    pdf.drawString(left + 12, table_top - 15, "Amount (SAR)")

    for index, (label, amount) in enumerate(rows):
        row_top = table_top - header_height - (index * row_height)
        is_net = index == len(rows) - 1
        if is_net:
            pdf.setFillColor(_INK_SOFT)
        elif index % 2 == 0:
            pdf.setFillColor(_WHITE)
        else:
            pdf.setFillColor(_PAPER_ALT)
        pdf.rect(left, row_top - row_height, right - left, row_height, fill=1, stroke=0)
        pdf.setStrokeColor(colors.Color(_LINE.red, _LINE.green, _LINE.blue, alpha=0.55))
        pdf.setLineWidth(0.4)
        pdf.line(left, row_top - row_height, right, row_top - row_height)

        text_colour = _WHITE if is_net else _INK
        pdf.setFillColor(text_colour)
        pdf.setFont(font_bold if is_net else font_regular, 9)
        pdf.drawRightString(right - 12, row_top - 16, _visual(label))

        amount_colour = _WHITE if is_net else (_RED if amount < 0 else _INK)
        pdf.setFillColor(amount_colour)
        pdf.setFont(font_bold if is_net else font_regular, 9)
        pdf.drawString(left + 12, row_top - 16, _money(amount))

    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 6.8)
    pdf.drawRightString(
        right,
        table_top - header_height - (len(rows) * row_height) - 10,
        _visual("أرقام توضيحية وهمية — لا تمثل راتباً حقيقياً ولا بيانات موظف حقيقية"),
    )


def _draw_warning(
    pdf: canvas.Canvas,
    *,
    font_regular: str,
    font_bold: str,
) -> None:
    """Draw the required awareness warning and the impact bullets."""
    width, _ = A4
    left = 48
    right = width - 48
    box_top = 415
    box_height = 160

    pdf.setFillColor(_RED_BG)
    pdf.setStrokeColor(_RED_LINE)
    pdf.setLineWidth(1.2)
    pdf.roundRect(left, box_top - box_height, right - left, box_height, 10, fill=1, stroke=1)
    pdf.setFillColor(_RED)
    pdf.rect(left, box_top - 4, right - left, 4, fill=1, stroke=0)

    pdf.setFillColor(colors.Color(_RED.red, _RED.green, _RED.blue, alpha=0.10))
    pdf.roundRect(right - 188, box_top - 28, 176, 18, 9, fill=1, stroke=0)
    pdf.setFillColor(_RED)
    pdf.setFont(font_bold, 7.5)
    pdf.drawCentredString(right - 100, box_top - 22, _visual("توقف — هذه محاكاة أمنية"))

    pdf.setFillColor(_RED)
    pdf.setFont(font_bold, 15)
    pdf.drawRightString(right - 18, box_top - 52, _visual("لقد قمت بتوصيل فلاشة مجهولة."))

    lines = _wrap(
        USB_WARNING,
        font=font_regular,
        size=10,
        max_width=(right - left) - 36,
        max_lines=4,
    )
    _draw_rtl_lines(
        pdf,
        lines,
        x_right=right - 18,
        y_top=box_top - 74,
        font=font_regular,
        size=10,
        leading=15,
        colour=_INK,
    )

    pdf.setFillColor(_GREEN)
    pdf.setFont(font_bold, 7.8)
    pdf.drawRightString(
        right - 18,
        box_top - box_height + 16,
        _visual("هذا الملف آمن تماماً: لا يحتوي على أي برامج أو أوامر تنفيذية."),
    )

    # Impact section.
    pdf.setFillColor(_INK)
    pdf.setFont(font_bold, 10.5)
    pdf.drawRightString(right, 224, _visual("ماذا كان يمكن أن يحدث في هجوم حقيقي؟"))
    bullets = [
        "تشفير ملفات العمل وطلب فدية مالية.",
        "سرقة بيانات الدخول وجلسات المتصفح المحفوظة.",
        "الانتقال إلى شبكة الشركة دون علمك.",
    ]
    y = 206
    for bullet in bullets:
        pdf.setFillColor(_RED)
        pdf.circle(right - 5, y + 3, 2.2, fill=1, stroke=0)
        pdf.setFillColor(_INK_SOFT)
        pdf.setFont(font_regular, 8.6)
        pdf.drawRightString(right - 14, y, _visual(bullet))
        y -= 16


def _draw_qr_footer(
    pdf: canvas.Canvas,
    *,
    recipient: USBDropRecipient,
    qr_png: bytes,
    support_email: str | None,
    font_regular: str,
    font_bold: str,
) -> None:
    """Draw the tracking QR, privacy note and page footer."""
    width, _ = A4
    left = 48
    right = width - 48

    card_x = left
    card_y = 64
    card_size = 108
    pdf.setFillColor(_WHITE)
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.8)
    pdf.roundRect(card_x, card_y, card_size, card_size, 8, fill=1, stroke=1)
    pdf.drawImage(
        ImageReader(io.BytesIO(qr_png)),
        card_x + 10,
        card_y + 10,
        width=card_size - 20,
        height=card_size - 20,
        preserveAspectRatio=True,
        mask="auto",
    )

    pdf.setFillColor(_INK)
    pdf.setFont(font_bold, 10.5)
    pdf.drawRightString(right, card_y + 94, _visual("امسح الرمز للاطلاع على التدريب"))
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 8.2)
    pdf.drawRightString(
        right,
        card_y + 78,
        _visual("سيُسجّل الفتح ويضيف الحدث إلى تقرير التوعية."),
    )
    pdf.setFillColor(_INK_SOFT)
    pdf.setFont(font_regular, 7.4)
    pdf.drawRightString(
        right,
        card_y + 61,
        _visual(f"معرّف التتبع: {recipient.tracking_uuid[:8]}"),
    )
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 7.2)
    pdf.drawRightString(
        right,
        card_y + 45,
        _visual("كل صفحة مخصصة لموظف واحد — لا تشارك الرمز مع زملائك."),
    )
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 7.2)
    pdf.drawRightString(
        right,
        card_y + 29,
        _visual("أبلغ فريق الأمن عند العثور على فلاشة مجهولة."),
    )

    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.7)
    pdf.line(left, 48, right, 48)
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 6.9)
    pdf.drawRightString(
        right,
        34,
        _visual(
            "محاكاة توعية مصرّح بها — لا تحتوي على أي برامج أو أوامر. "
            "لا تُستخدم بيانات رواتب حقيقية."
        ),
    )
    if support_email:
        pdf.drawString(left, 34, _text(support_email)[:80])


def _draw_page(
    pdf: canvas.Canvas,
    *,
    organization: Any,
    recipient: USBDropRecipient,
    copy: USBDropCopy,
    qr_png: bytes,
    support_email: str | None,
) -> None:
    """Draw one A4 USB-awareness page."""
    width, height = A4
    font_regular, font_bold = _fonts()

    pdf.setFillColor(_PAPER)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    # A faint paper texture made of two translucent bands.
    pdf.setFillColor(colors.Color(255, 255, 255, alpha=0.55))
    pdf.rect(0, 0, width, height - 96, fill=1, stroke=0)

    _draw_header(
        pdf,
        organization=organization,
        copy=copy,
        font_regular=font_regular,
        font_bold=font_bold,
    )
    _draw_employee_panel(
        pdf,
        recipient=recipient,
        copy=copy,
        font_regular=font_regular,
        font_bold=font_bold,
    )
    _draw_salary_table(pdf, font_regular=font_regular, font_bold=font_bold)
    _draw_warning(pdf, font_regular=font_regular, font_bold=font_bold)
    _draw_qr_footer(
        pdf,
        recipient=recipient,
        qr_png=qr_png,
        support_email=support_email,
        font_regular=font_regular,
        font_bold=font_bold,
    )
    pdf.showPage()


def build_usb_drop_pack(
    *,
    organization: Any,
    campaign: Any,
    recipients: Iterable[USBDropRecipient],
    channel_config: Mapping[str, Any] | None = None,
    support_email: str | None = None,
    copy: USBDropCopy | None = None,
) -> bytes:
    """Build a safe, multi-page A4 USB-drop PDF, one page per recipient.

    Args:
        organization: Organization ORM object (name, colour, logo).
        campaign: Campaign ORM object, used for the PDF metadata.
        recipients: Recipients with unique tracking URLs.
        channel_config: Campaign ``channel_config`` JSON.
        support_email: Optional support address printed in the footer.

    Returns:
        PDF bytes.  The document contains one page per recipient and no
        executable, embedded-file or JavaScript content.

    Raises:
        ValueError: When no recipient is supplied.
    """
    company = _text(getattr(organization, "name", None)) or "Our Company"
    copy = copy or resolve_usb_copy(channel_config)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"{company} — USB awareness document")
    pdf.setAuthor("HUMINT Shield")
    pdf.setSubject(
        "Authorized security-awareness USB-drop exercise. "
        f"Campaign: {_text(getattr(campaign, 'name', ''))}"
    )
    pdf.setKeywords("security awareness, USB drop, simulation, safe PDF")

    generated = 0
    for recipient in recipients:
        qr_png = generate_qr_png(recipient.tracking_url)
        _draw_page(
            pdf,
            organization=organization,
            recipient=recipient,
            copy=copy,
            qr_png=qr_png,
            support_email=support_email,
        )
        generated += 1
    if generated == 0:
        raise ValueError("at least one USB-document recipient is required")
    pdf.save()
    return buffer.getvalue()


def content_disposition(document_name: str) -> str:
    """Return an RFC 5987 ``Content-Disposition`` value for an Arabic name."""
    name = safe_document_name(document_name)
    encoded = quote(name, safe="")
    return (
        'attachment; filename="salary_next_month.pdf"; '
        f"filename*=UTF-8''{encoded}"
    )


def safe_html_name(value: Any) -> str:
    """Return a header-safe ``.html`` document name."""
    name = _text(value) or HTML_DOCUMENT_NAME
    name = name.replace("\\", "-").replace("/", "-").replace('"', "'")
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    if not name:
        name = HTML_DOCUMENT_NAME
    if not name.lower().endswith(".html"):
        name = f"{name}.html"
    return name[:120]


def content_disposition_html(document_name: str = HTML_DOCUMENT_NAME) -> str:
    """Return an RFC 5987 attachment header for the Arabic HTML file name."""
    name = safe_html_name(document_name)
    encoded = quote(name, safe="")
    return (
        'attachment; filename="salary_secrets.html"; '
        f"filename*=UTF-8''{encoded}"
    )


#: The beacon injected into every HTML USB document.
#:
#: It is deliberately dependency-free, works from ``file://`` and never blocks
#: the warning page.  On open it collects a forensic profile (device, browser
#: and OS, screen, GPU, CPU/RAM, battery, storage, network quality, timezone and
#: local time, the full source path of the opened file, optional GPS, WebRTC
#: local addresses) and posts it as a *simple* request so no CORS preflight is
#: needed.  When the machine is offline the packet is kept in ``localStorage``
#: and retried on ``online``, on tab focus and every 20 seconds, so an offline
#: open still reaches the monitoring board as soon as the machine reconnects.
_USB_BEACON_SCRIPT = r"""
(function () {
  "use strict";

  var trackingUrl = __TRACKING_URL__;
  var documentName = __DOCUMENT_NAME__;
  var queueKey = "humint_usb_queue_v2";
  var deviceKey = "humint_usb_device_v2";
  var statusEl = document.getElementById("report-state");

  function setStatus(message, tone) {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.setAttribute("data-tone", tone || "info");
  }

  function safe(fn, fallback) {
    try {
      var value = fn();
      return value === undefined || value === null ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function readStore(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function newId() {
    return "usb-" + new Date().getTime().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  function fingerprint(parts) {
    var text = parts.join("|");
    var hash = 2166136261;
    for (var i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return ("00000000" + (hash >>> 0).toString(16)).slice(-8);
  }

  function gpuInfo() {
    return safe(function () {
      var canvas = document.createElement("canvas");
      var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) return {};
      var debug = gl.getExtension("WEBGL_debug_renderer_info");
      return {
        vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
        renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)
      };
    }, {});
  }

  function deviceInfo() {
    var nav = navigator;
    var data = nav.userAgentData || null;
    var brands = [];
    if (data && data.brands) {
      for (var i = 0; i < data.brands.length; i += 1) {
        brands.push(data.brands[i].brand + " " + data.brands[i].version);
      }
    }
    var ua = nav.userAgent || "";
    var os = safe(function () {
      if (/Windows NT 10/.test(ua)) return "Windows 10/11";
      if (/Windows NT 6\.1/.test(ua)) return "Windows 7";
      if (/Mac OS X/.test(ua)) return "macOS";
      if (/Android/.test(ua)) return "Android";
      if (/iPhone|iPad/.test(ua)) return "iOS";
      if (/Linux/.test(ua)) return "Linux";
      return null;
    }, null);
    var browser = safe(function () {
      if (/Edg\//.test(ua)) return "Edge";
      if (/OPR\//.test(ua)) return "Opera";
      if (/Firefox\//.test(ua)) return "Firefox";
      if (/Chrome\//.test(ua)) return "Chrome";
      if (/Safari\//.test(ua)) return "Safari";
      return null;
    }, null);
    return {
      user_agent: ua,
      ua_platform: data ? data.platform : nav.platform,
      ua_platform_version: data ? data.platformVersion : null,
      ua_architecture: data ? data.architecture : null,
      ua_bitness: data ? data.bitness : null,
      ua_model: data ? data.model : null,
      ua_mobile: data ? data.mobile : null,
      ua_brands: brands.join(", "),
      platform: nav.platform,
      vendor: nav.vendor,
      os: os,
      browser: browser,
      language: nav.language,
      languages: (nav.languages || []).slice(0, 8).join(", "),
      timezone: safe(function () { return Intl.DateTimeFormat().resolvedOptions().timeZone; }, null),
      timezone_offset_min: new Date().getTimezoneOffset(),
      local_time: new Date().toString(),
      hardware_concurrency: nav.hardwareConcurrency || null,
      device_memory_gb: nav.deviceMemory || null,
      // Firefox/Safari do not expose deviceMemory; the V8 heap cap is the only
      // remaining hint, so it is labelled as an estimate instead of RAM.
      estimate_ram_gb: safe(function () {
        var heap = window.performance && window.performance.memory
          ? window.performance.memory.jsHeapSizeLimit
          : null;
        return heap ? Math.round((heap / 1073741824) * 10) / 10 : null;
      }, null),
      oscpu: nav.oscpu || null,
      max_touch_points: nav.maxTouchPoints || 0,
      cookies_enabled: nav.cookieEnabled === true,
      pdf_viewer_enabled: nav.pdfViewerEnabled === undefined ? null : nav.pdfViewerEnabled,
      do_not_track: nav.doNotTrack || window.doNotTrack || null,
      hostname: null,
      username: null,
      domain: null,
      source_path: null
    };
  }

  function screenInfo() {
    var screen = window.screen || {};
    return {
      width: screen.width || null,
      height: screen.height || null,
      avail_width: screen.availWidth || null,
      avail_height: screen.availHeight || null,
      color_depth: screen.colorDepth || null,
      pixel_depth: screen.pixelDepth || null,
      orientation: screen.orientation ? screen.orientation.type : null,
      pixel_ratio: window.devicePixelRatio || 1,
      inner_width: window.innerWidth || null,
      inner_height: window.innerHeight || null
    };
  }

  function networkInfo() {
    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;
    return {
      online: navigator.onLine === true,
      effective_type: conn ? conn.effectiveType : null,
      connection_type: conn ? conn.type : null,
      downlink_mbps: conn && conn.downlink !== undefined ? conn.downlink : null,
      rtt_ms: conn && conn.rtt !== undefined ? conn.rtt : null,
      save_data: conn && conn.saveData !== undefined ? conn.saveData : null
    };
  }

  function sourceInfo() {
    var href = String(window.location.href || "");
    var path = safe(function () {
      return decodeURIComponent(href.replace(/^file:\/\/\//, "").replace(/^file:\/\//, ""));
    }, href);
    var stored = readStore(deviceKey, null);
    return {
      href: href,
      path: path,
      protocol: String(window.location.protocol || ""),
      opened_at: new Date().toISOString(),
      first_seen_at: stored && stored.first_seen ? stored.first_seen : null,
      referrer: String(document.referrer || "")
    };
  }

  function webrtcAddresses(done) {
    var addresses = [];
    var finished = false;
    function finish() {
      if (finished) return;
      finished = true;
      done(addresses);
    }
    var timer = setTimeout(finish, 1400);
    try {
      var Ctor = window.RTCPeerConnection || window.webkitRTCPeerConnection;
      if (!Ctor) {
        clearTimeout(timer);
        finish();
        return;
      }
      var pc = new Ctor({ iceServers: [] });
      pc.createDataChannel("probe");
      pc.onicecandidate = function (event) {
        if (!event || !event.candidate || !event.candidate.candidate) {
          clearTimeout(timer);
          finish();
          return;
        }
        var value = String(event.candidate.candidate).split(" ")[4];
        if (value && addresses.indexOf(value) === -1) addresses.push(value);
      };
      pc.createOffer().then(function (offer) { return pc.setLocalDescription(offer); }).catch(function () {});
      setTimeout(function () {
        try { pc.close(); } catch (error) {}
        clearTimeout(timer);
        finish();
      }, 1300);
    } catch (error) {
      clearTimeout(timer);
      finish();
    }
  }

  function powerInfo(done) {
    try {
      if (!navigator.getBattery) {
        done({});
        return;
      }
      navigator.getBattery().then(function (cell) {
        done({ level: Math.round(cell.level * 1000) / 1000, charging: cell.charging });
      }).catch(function () { done({}); });
    } catch (error) {
      done({});
    }
  }

  function storageInfo(done) {
    try {
      if (!navigator.storage || !navigator.storage.estimate) {
        done({});
        return;
      }
      navigator.storage.estimate().then(function (estimate) {
        done({
          quota_mb: Math.round((estimate.quota || 0) / 1048576),
          usage_mb: Math.round((estimate.usage || 0) / 1048576)
        });
      }).catch(function () { done({}); });
    } catch (error) {
      done({});
    }
  }

  function geoInfo(done) {
    var finish = function (value) { done(value || {}); };
    try {
      if (!navigator.geolocation || !navigator.permissions || !navigator.permissions.query) {
        finish({});
        return;
      }
      navigator.permissions.query({ name: "geolocation" }).then(function (permission) {
        if (permission.state !== "granted") {
          finish({ permission: permission.state });
          return;
        }
        navigator.geolocation.getCurrentPosition(
          function (position) {
            finish({
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
              accuracy_m: Math.round(position.coords.accuracy),
              permission: "granted"
            });
          },
          function () { finish({ permission: "unavailable" }); },
          { timeout: 2500, maximumAge: 60000, enableHighAccuracy: false }
        );
      }).catch(function () { finish({}); });
    } catch (error) {
      finish({});
    }
  }

  function buildEvent() {
    var device = deviceInfo();
    var screen = screenInfo();
    var gpu = gpuInfo();
    var event = {
      schema: 2,
      event: "usb_document_opened",
      client_event_id: newId(),
      document: documentName,
      fingerprint: fingerprint([
        device.user_agent || "",
        device.ua_platform || "",
        device.hardware_concurrency || "",
        device.device_memory_gb || "",
        screen.width || "",
        screen.height || "",
        screen.pixel_ratio || "",
        gpu.renderer || "",
        device.timezone || ""
      ]),
      source: sourceInfo(),
      device: device,
      screen: screen,
      gpu: gpu,
      network: networkInfo(),
      webrtc: { local_ips: [] },
      power: {},
      storage: {},
      geolocation: {},
      queue: { offline_at_capture: navigator.onLine === false }
    };
    return event;
  }

  function enrich(event) {
    return new Promise(function (resolve) {
      var settled = false;
      var finish = function () {
        if (settled) return;
        settled = true;
        resolve(event);
      };
      setTimeout(finish, 2600);
      webrtcAddresses(function (addresses) {
        event.webrtc.local_ips = addresses;
        // Chrome/Firefox mask private IPs with an mDNS name; it is still the
        // only per-host label a sandboxed page can obtain.
        for (var i = 0; i < addresses.length; i += 1) {
          if (String(addresses[i]).indexOf(".local") !== -1) {
            event.webrtc.mdns_hostname = addresses[i];
            if (!event.device.hostname) event.device.hostname = addresses[i];
            break;
          }
        }
        finish();
      });
      powerInfo(function (info) { event.power = info; });
      storageInfo(function (info) { event.storage = info; });
      geoInfo(function (info) { event.geolocation = info; });
    });
  }

  function pixelFallback() {
    try {
      var image = new Image();
      image.referrerPolicy = "no-referrer";
      image.src = trackingUrl;
      return true;
    } catch (error) {
      return false;
    }
  }

  function beacon(event) {
    try {
      if (!navigator.sendBeacon) return Promise.resolve(false);
      var blob = new Blob([JSON.stringify(event)], { type: "text/plain;charset=UTF-8" });
      return Promise.resolve(navigator.sendBeacon(trackingUrl, blob) === true);
    } catch (error) {
      return Promise.resolve(false);
    }
  }

  function postEvent(event) {
    // ``sendBeacon`` reports success as soon as the browser queues the request,
    // even when the host is offline, so it can never be used to decide whether
    // a packet arrived.  ``fetch`` is the only reliable signal; the beacon is
    // kept strictly as a fallback for browsers without fetch.
    if (typeof window.fetch === "function") {
      try {
        return window.fetch(trackingUrl, {
          method: "POST",
          mode: "no-cors",
          cache: "no-store",
          credentials: "omit",
          keepalive: true,
          headers: { "Content-Type": "text/plain;charset=UTF-8" },
          body: JSON.stringify(event)
        }).then(
          function () { return true; },
          function () { return false; }
        );
      } catch (error) {
        return Promise.resolve(false);
      }
    }
    return beacon(event);
  }

  function queueEvent(event) {
    var queue = readStore(queueKey, []);
    if (!(queue instanceof Array)) queue = [];
    var exists = false;
    for (var i = 0; i < queue.length; i += 1) {
      if (queue[i] && queue[i].client_event_id === event.client_event_id) exists = true;
    }
    if (!exists) queue.push(event);
    writeStore(queueKey, queue.slice(-20));
  }

  function dropEvent(id) {
    var queue = readStore(queueKey, []);
    if (!(queue instanceof Array)) return;
    var next = [];
    for (var i = 0; i < queue.length; i += 1) {
      if (queue[i] && queue[i].client_event_id !== id) next.push(queue[i]);
    }
    writeStore(queueKey, next);
  }

  var flushing = false;

  function flushQueue() {
    if (flushing) return;
    var queue = readStore(queueKey, []);
    if (!(queue instanceof Array) || queue.length === 0) return;
    flushing = true;
    var item = queue[0];
    postEvent(item).then(function (ok) {
      flushing = false;
      if (ok) {
        dropEvent(item.client_event_id);
        flushQueue();
      }
    });
  }

  function report() {
    var event = buildEvent();
    writeStore(deviceKey, { first_seen: event.source.opened_at, fingerprint: event.fingerprint });
    setStatus("Sending the open event and this device's profile to the monitoring board…", "info");
    enrich(event).then(function (ready) {
      postEvent(ready).then(function (ok) {
        if (!ok) {
          pixelFallback();
          queueEvent(ready);
          setStatus(
            navigator.onLine === false
              ? "No internet connection right now. The report is stored and is sent automatically the moment the device reconnects."
              : "The monitoring server could not be reached. The report is stored and retried automatically.",
            "warn"
          );
          return;
        }
        setStatus("Recorded on the monitoring board: this open, the device profile, the network and the location.", "ok");
        flushQueue();
      });
    });
  }

  window.addEventListener("online", function () {
    setStatus("Connection restored — sending the stored report…", "info");
    flushQueue();
  });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) flushQueue();
  });
  setInterval(flushQueue, 20000);
  // A document re-opened later on a connected machine drains yesterday's queue
  // immediately instead of waiting for the first interval tick.
  setTimeout(flushQueue, 1500);
  setTimeout(function () {
    try {
      report();
    } catch (error) {
      pixelFallback();
    }
  }, 120);
})();
"""


def build_usb_html(
    *,
    organization: Any,
    recipient: USBDropRecipient,
    training_url: str,
    support_email: str | None = None,
    document_name: str | None = None,
) -> bytes:
    """Build the safe standalone HTML USB artefact.

    The file is intentionally simple and inert.  On open it performs one
    ``no-cors`` GET to the per-recipient USB tracking endpoint, then displays a
    full-screen red warning.  There is no credential collection, no local-file
    access, no download, and no executable payload.  A visible training link
    lets the recipient continue to the micro-learning page after the warning.

    Args:
        organization: Organization ORM object (name/branding).
        recipient: Recipient identity and tracking URL.
        training_url: Absolute URL of the post-warning micro-training page.
        support_email: Optional security-team address displayed in the footer.

    Returns:
        UTF-8 HTML bytes ready to write to ``الرواتب_السرية.html``.
    """
    company = html.escape(_text(getattr(organization, "name", None)) or "Our Company")
    employee = html.escape(
        _text(recipient.name) or _text(recipient.email) or "زميلنا العزيز"
    )
    department = html.escape(_text(recipient.department) or "—")
    tracking_url = json.dumps(recipient.tracking_url or "", ensure_ascii=False)
    safe_training_url = html.escape(training_url or "", quote=True)
    warning = html.escape(USB_HTML_WARNING)
    beacon_script = _USB_BEACON_SCRIPT.replace(
        "__TRACKING_URL__", tracking_url
    ).replace(
        "__DOCUMENT_NAME__",
        json.dumps(safe_html_name(document_name or HTML_DOCUMENT_NAME), ensure_ascii=False),
    )
    support = html.escape(_text(support_email) or "", quote=True)
    support_block = (
        f'<p class="support">للإبلاغ: <span dir="ltr">{support}</span></p>'
        if support
        else ""
    )
    document = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>الرواتب السرية — تحذير أمني</title>
<style>
  :root {{
    color-scheme: dark;
    --paper: #f4efe4;
    --ink: #172033;
    --muted: #64748b;
    --red: #b91c1c;
    --red-deep: #7f1d1d;
    --white: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    overflow: hidden;
    background: #080b12;
    font-family: "Segoe UI", Tahoma, Arial, sans-serif;
    color: var(--ink);
  }}
  .document {{
    position: fixed;
    inset: 0;
    padding: 6vh 7vw;
    background:
      radial-gradient(circle at 18% 20%, rgba(14, 116, 144, .16), transparent 34%),
      linear-gradient(145deg, #e9e2d3, var(--paper));
    filter: blur(1.4px) saturate(.8);
    user-select: none;
  }}
  .doc-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 2px solid #cbd5e1;
    padding-bottom: 18px;
  }}
  .brand {{ display: flex; align-items: center; gap: 14px; font-weight: 800; font-size: 1.2rem; }}
  .mark {{
    width: 48px; height: 48px; border-radius: 14px;
    background: #0e7490; color: white; display: grid; place-items: center;
    font-size: 1.2rem; box-shadow: 0 12px 30px rgba(14, 116, 144, .3);
  }}
  .conf {{ color: var(--red); font-weight: 900; letter-spacing: .16em; font-size: .8rem; }}
  .doc-title {{ margin: 34px 0 4px; font-size: clamp(1.8rem, 4vw, 3rem); }}
  .doc-sub {{ margin: 0 0 26px; color: var(--muted); }}
  .identity {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 26px; }}
  .identity div {{ background: rgba(255,255,255,.72); border: 1px solid #d8dee9; border-radius: 14px; padding: 16px 20px; }}
  .identity small {{ display: block; color: var(--muted); margin-bottom: 6px; }}
  .identity strong {{ font-size: 1.02rem; }}
  table {{ width: 100%; border-collapse: collapse; border-radius: 16px; overflow: hidden; background: rgba(255,255,255,.78); }}
  th, td {{ padding: 15px 20px; text-align: right; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #172033; color: white; font-size: .86rem; }}
  tr:last-child td {{ border-bottom: 0; font-weight: 900; background: #172033; color: white; }}
  .doc-note {{ margin-top: 18px; color: var(--muted); font-size: .78rem; }}
  .overlay {{
    position: fixed;
    inset: 0;
    z-index: 10;
    display: grid;
    place-items: center;
    padding: clamp(18px, 4vw, 54px);
    background:
      radial-gradient(circle at 50% 30%, rgba(255,255,255,.12), transparent 34%),
      radial-gradient(circle at 50% 110%, rgba(0,0,0,.5), transparent 62%),
      linear-gradient(145deg, #991b1b 0%, #7f1d1d 48%, #450a0a 100%);
    animation: alarm 1.6s ease-in-out infinite alternate;
  }}
  @keyframes alarm {{
    from {{ box-shadow: inset 0 0 0 0 rgba(254, 202, 202, .0); }}
    to {{ box-shadow: inset 0 0 120px 24px rgba(254, 202, 202, .16); }}
  }}
  .alert-card {{
    width: min(1180px, 96vw);
    border: 2px solid rgba(254, 202, 202, .55);
    border-radius: 28px;
    background: rgba(69, 10, 10, .62);
    box-shadow: 0 34px 120px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.14);
    padding: clamp(24px, 4vw, 58px);
    text-align: center;
    color: var(--white);
    backdrop-filter: blur(10px);
  }}
  .stop {{
    display: inline-grid; place-items: center;
    width: clamp(64px, 9vw, 104px); height: clamp(64px, 9vw, 104px);
    margin-bottom: 18px;
    border-radius: 50%;
    background: #fff; color: #991b1b;
    font-weight: 1000; font-size: clamp(.92rem, 1.7vw, 1.35rem);
    letter-spacing: .04em;
    box-shadow: 0 0 0 12px rgba(255,255,255,.14), 0 20px 40px rgba(0,0,0,.35);
  }}
  .eyebrow {{
    margin: 0 0 14px;
    color: #fecaca;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    font-size: clamp(.72rem, 1.4vw, .95rem);
  }}
  h1 {{
    margin: 0 auto 22px;
    max-width: 1050px;
    font-size: clamp(2rem, 5.2vw, 5.4rem);
    line-height: 1.34;
    font-weight: 1000;
    color: #fff;
    text-shadow: 0 3px 0 rgba(0,0,0,.28), 0 18px 46px rgba(0,0,0,.45);
  }}
  .explain {{
    max-width: 860px;
    margin: 0 auto 24px;
    color: #fee2e2;
    font-size: clamp(.96rem, 1.7vw, 1.22rem);
    line-height: 1.9;
  }}
  .cta {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 54px;
    padding: 0 30px;
    border-radius: 999px;
    background: #fff;
    color: #7f1d1d;
    text-decoration: none;
    font-weight: 900;
    font-size: 1.05rem;
    box-shadow: 0 16px 42px rgba(0,0,0,.28);
  }}
  .cta:hover {{ background: #fef2f2; }}
  .support {{ margin: 18px 0 0; color: #fecaca; font-size: .9rem; }}
  .report {{
    margin: 16px auto 0;
    max-width: 820px;
    font-size: .86rem;
    line-height: 1.7;
    color: #fee2e2;
  }}
  .report[data-tone="ok"] {{ color: #bbf7d0; }}
  .report[data-tone="warn"] {{ color: #fde68a; }}
  .safety {{
    margin: 16px 0 0;
    color: rgba(254, 226, 226, .78);
    font-size: .78rem;
    line-height: 1.7;
  }}
  @media (max-width: 640px) {{
    .identity {{ grid-template-columns: 1fr; }}
    .overlay {{ padding: 14px; }}
    .alert-card {{ padding: 24px 18px; border-radius: 20px; }}
    h1 {{ line-height: 1.45; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .overlay {{ animation: none; }}
  }}
</style>
</head>
<body>
<main class="document" aria-hidden="true">
  <div class="doc-head">
    <div class="brand"><span class="mark">H</span><span>{company}</span></div>
    <span class="conf">CONFIDENTIAL</span>
  </div>
  <h2 class="doc-title">كشف الرواتب — سري للغاية</h2>
  <p class="doc-sub">ملف داخلي افتراضي أُنشئ لتمرين توعية أمنية مصرّح به.</p>
  <section class="identity">
    <div><small>الموظف</small><strong>{employee}</strong></div>
    <div><small>القسم</small><strong>{department}</strong></div>
  </section>
  <table>
    <thead><tr><th>البند</th><th>المبلغ (ريال)</th></tr></thead>
    <tbody>
      <tr><td>الراتب الأساسي</td><td>8,500</td></tr>
      <tr><td>بدل السكن</td><td>2,500</td></tr>
      <tr><td>بدل النقل</td><td>800</td></tr>
      <tr><td>بدلات أخرى</td><td>400</td></tr>
      <tr><td>استقطاعات</td><td>-450</td></tr>
      <tr><td>صافي الراتب</td><td>11,750</td></tr>
    </tbody>
  </table>
  <p class="doc-note">جميع الأرقام وهمية ولا تمثل راتباً حقيقياً أو بيانات موظف حقيقي.</p>
</main>
<div class="overlay" role="alert" aria-live="assertive">
  <div class="alert-card">
    <div class="stop" aria-hidden="true">STOP</div>
    <p class="eyebrow">محاكاة توعية مصرّح بها — ليست هجوماً حقيقياً</p>
    <h1>{warning}</h1>
    <p class="explain">
      هذا الملف لا يحتوي على أي برامج أو أوامر تنفيذية، ولم يقرأ أي ملف من جهازك.
      في هجوم حقيقي، كانت فلاشة مجهولة كهذه قد تُستخدم لسرقة البيانات أو نشر برامج الفدية.
    </p>
    <a class="cta" href="{safe_training_url}">ابدأ التدريب الآن</a>
    <p class="report" id="report-state" data-tone="info">
      جارٍ تسجيل بيانات الفتح والجهاز في مركز المراقبة…
    </p>
    {support_block}
    <p class="safety">
      تم تسجيل هذا الفتح في سجل التوعية وربطه بهوية الموظف المخصص له الملف.
      أبلغ فريق الأمن عند العثور على أي وسيط تخزين مجهول.
    </p>
  </div>
</div>
<script>
{beacon_script}
</script>
</body>
</html>
"""
    return document.encode("utf-8")


#: File names of the optional local identity collector.  The pair sits beside
#: the lure on the stick and never runs itself: the browser cannot read the
#: Windows account or the real machine name, this script can.
IDENTITY_TOOL_CMD_NAME = "HUMINT_Identity_Check.cmd"
IDENTITY_TOOL_PS1_NAME = "HUMINT_Identity_Check.ps1"

#: The collector itself.  It reads identity only (account, machine, domain, OS
#: build, hardware, network), posts it once to the campaign's probe endpoint and
#: queues it in ``%TEMP%`` when the host is offline.  It changes nothing, reads
#: no user files and stores no copy of the profile.
_USB_IDENTITY_TOOL_PS1 = r'''
#Requires -Version 3.0
<#
  HUMINT Shield - optional device identity collector.

  Authorized security-awareness exercise only.  A local HTML page cannot read
  the signed-in Windows account or the real computer name; this script fills
  exactly that gap.  It changes nothing on the machine, installs nothing, reads
  no user files and keeps no copy: the only side effect is one HTTPS POST to the
  campaign's tracking endpoint.  When the host is offline the packet is queued
  in %TEMP% and retried on the next run.
#>
$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference = "SilentlyContinue"
$endpoint = "__PROBE_URL__"
$queuePath = Join-Path $env:TEMP "humint_usb_identity_queue.json"

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch { }

function Send-Packet {
    param($Packet)
    try {
        $body = $Packet | ConvertTo-Json -Depth 6 -Compress
        Invoke-RestMethod -Method Post -Uri $endpoint -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 25 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Read-Queue {
    if (-not (Test-Path -LiteralPath $queuePath)) { return @() }
    try {
        $raw = Get-Content -LiteralPath $queuePath -Raw
        if (-not $raw) { return @() }
        $items = $raw | ConvertFrom-Json
        if ($null -eq $items) { return @() }
        return @($items)
    } catch {
        return @()
    }
}

function Save-Queue {
    param($Items)
    try {
        $trimmed = @($Items | Select-Object -Last 10)
        if ($trimmed.Count -eq 0) {
            Remove-Item -LiteralPath $queuePath -Force
        } else {
            ($trimmed | ConvertTo-Json -Depth 6 -Compress) | Set-Content -LiteralPath $queuePath -Encoding UTF8
        }
    } catch { }
}

function Get-Identity {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $bios = Get-CimInstance -ClassName Win32_BIOS
    $cpu = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1

    $nic = Get-NetIPConfiguration | Where-Object { $null -ne $_.IPv4DefaultGateway } | Select-Object -First 1
    if (-not $nic) {
        $nic = Get-NetIPConfiguration | Where-Object { $null -ne $_.IPv4Address } | Select-Object -First 1
    }

    $isAdmin = $false
    try {
        $principal = New-Object -TypeName Security.Principal.WindowsPrincipal -ArgumentList ([Security.Principal.WindowsIdentity]::GetCurrent())
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { }

    $uptimeMinutes = $null
    if ($os.LastBootUpTime) {
        $uptimeMinutes = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalMinutes, 0)
    }

    $installedAt = $null
    if ($os.InstallDate) {
        $installedAt = $os.InstallDate.ToUniversalTime().ToString("o")
    }

    $ramGb = $null
    if ($computer.TotalPhysicalMemory) {
        $ramGb = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
    }

    $localIp = $null
    $mac = $null
    $gateway = $null
    $dns = $null
    if ($nic) {
        $address = @($nic.IPv4Address)[0]
        if ($address) { $localIp = $address.IPAddress }
        if ($nic.NetAdapter) { $mac = $nic.NetAdapter.MacAddress }
        if ($nic.IPv4DefaultGateway) { $gateway = @($nic.IPv4DefaultGateway)[0].NextHop }
        $dns = (@($nic.DNSServer) | ForEach-Object { $_.ServerAddresses } | Select-Object -First 4) -join ", "
    }

    $timezone = $null
    try { $timezone = (Get-TimeZone).Id } catch { $timezone = [TimeZoneInfo]::Local.Id }

    return [ordered]@{
        source          = "local_tool"
        client_event_id = [guid]::NewGuid().ToString()
        collected_at    = (Get-Date).ToUniversalTime().ToString("o")
        script          = "__SCRIPT_NAME__"
        username        = $env:USERNAME
        user_domain     = $env:USERDOMAIN
        logged_on_user  = $computer.UserName
        hostname        = $env:COMPUTERNAME
        domain          = $computer.Domain
        workgroup       = $computer.Workgroup
        os_caption      = $os.Caption
        os_version      = $os.Version
        os_build        = $os.BuildNumber
        os_arch         = $os.OSArchitecture
        installed_at    = $installedAt
        last_boot       = $os.LastBootUpTime
        manufacturer    = $computer.Manufacturer
        model           = $computer.Model
        serial          = $bios.SerialNumber
        cpu             = $cpu.Name
        cpu_cores       = $cpu.NumberOfCores
        cpu_logical     = $cpu.NumberOfLogicalProcessors
        ram_gb          = $ramGb
        local_ip        = $localIp
        mac             = $mac
        gateway         = $gateway
        dns_servers     = $dns
        session_name    = $env:SESSIONNAME
        powershell      = $PSVersionTable.PSVersion.ToString()
        timezone        = $timezone
        uptime_minutes  = $uptimeMinutes
        is_admin        = $isAdmin
    }
}

Write-Host ""
Write-Host "  HUMINT Shield  -  authorized security-awareness exercise" -ForegroundColor Cyan
Write-Host "  Reading this device's identity for the exercise record..." -ForegroundColor Gray
Write-Host ""

$queue = @(Read-Queue)
if ($queue.Count -gt 0) {
    $pending = @()
    foreach ($item in $queue) {
        if (-not (Send-Packet $item)) { $pending += $item }
    }
    Save-Queue $pending
    if ($pending.Count -ne $queue.Count) {
        Write-Host "  A report captured earlier on this machine was delivered." -ForegroundColor DarkGray
    }
}

$identity = Get-Identity
if (Send-Packet $identity) {
    Write-Host "  Device identity recorded on the monitoring board." -ForegroundColor Green
    Write-Host ("  Machine: {0}    Account: {1}\{2}" -f $identity.hostname, $identity.user_domain, $identity.username) -ForegroundColor Green
} else {
    $queue = @(Read-Queue)
    $queue += $identity
    Save-Queue $queue
    Write-Host "  No connection to the monitoring server right now." -ForegroundColor Yellow
    Write-Host "  The report is stored on this machine and is sent on the next run." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  You can close this window." -ForegroundColor DarkGray
Start-Sleep -Seconds 6
'''

#: Double-clickable launcher.  ``-ExecutionPolicy Bypass`` keeps a restrictive
#: machine policy from turning the collector into an opaque failure.
_USB_IDENTITY_TOOL_CMD = r'''@echo off
setlocal
title HUMINT Shield - Authorized security-awareness exercise
echo.
echo   HUMINT Shield  -  authorized awareness exercise
echo   Running the device identity check...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0__SCRIPT_NAME__"
if errorlevel 1 (
  echo.
  echo   The check could not run. If Windows blocked the script, right-click
  echo   __SCRIPT_NAME__, choose Properties and tick Unblock, then try again.
  echo.
  pause
)
endlocal
'''


def build_usb_identity_tool(
    *, recipient: USBDropRecipient, base_url: str
) -> list[tuple[str, bytes]]:
    """Build the optional local identity collector for one USB recipient.

    The browser is deliberately denied the Windows account and the real machine
    name, so the only honest way to capture them is a small script copied to the
    stick next to the lure.  It is never required: without it the document's own
    telemetry remains the record.

    Args:
        recipient: The recipient whose tracking UUID identifies the drop.
        base_url: Public API origin, e.g. ``https://api.example.com``.

    Returns:
        ``(file_name, content)`` pairs for the ``.cmd`` launcher and the
        PowerShell collector, ready for :func:`deploy_files`.
    """
    base = (base_url or "").rstrip("/")
    probe_url = f"{base}/api/v1/track/usb/{recipient.tracking_uuid}/device"
    script = _USB_IDENTITY_TOOL_PS1.replace("__PROBE_URL__", probe_url).replace(
        "__SCRIPT_NAME__", IDENTITY_TOOL_PS1_NAME
    )
    launcher = _USB_IDENTITY_TOOL_CMD.replace("__SCRIPT_NAME__", IDENTITY_TOOL_PS1_NAME)
    # CRLF keeps the batch file's labels and echo lines intact on Windows.
    launcher_bytes = launcher.replace("\n", "\r\n").encode("ascii", "replace")
    # A BOM makes Windows PowerShell 5.1 read the file as UTF-8 regardless of
    # the machine's legacy code page.
    script_bytes = ("\ufeff" + script.lstrip("\ufeff")).encode("utf-8")
    return [
        (IDENTITY_TOOL_CMD_NAME, launcher_bytes),
        (IDENTITY_TOOL_PS1_NAME, script_bytes),
    ]


__all__ = [
    "DEFAULT_DOCUMENT_NAME",
    "DEFAULT_MONTH_LABEL",
    "HTML_DOCUMENT_NAME",
    "IDENTITY_TOOL_CMD_NAME",
    "IDENTITY_TOOL_PS1_NAME",
    "USB_HTML_WARNING",
    "USB_WARNING",
    "USBDropCopy",
    "USBDropRecipient",
    "build_usb_drop_pack",
    "build_usb_html",
    "build_usb_identity_tool",
    "content_disposition",
    "content_disposition_html",
    "resolve_usb_copy",
    "safe_document_name",
    "safe_html_name",
]
