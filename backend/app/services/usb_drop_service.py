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
) -> USBDropCopy:
    """Resolve document metadata from ``campaigns.channel_config.usb``."""
    config = dict(channel_config or {})
    raw = config.get("usb")
    usb = dict(raw) if isinstance(raw, Mapping) else {}
    document_name = safe_document_name(usb.get("document_name"))
    month_label = _text(usb.get("month_label")) or _next_month_label(now)
    return USBDropCopy(
        document_name=document_name,
        month_label=month_label[:80],
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
    copy = resolve_usb_copy(channel_config)
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


def build_usb_html(
    *,
    organization: Any,
    recipient: USBDropRecipient,
    training_url: str,
    support_email: str | None = None,
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
    {support_block}
    <p class="safety">
      تم تسجيل هذا الفتح في سجل التوعية وربطه بهوية الموظف المخصص له الملف.
      أبلغ فريق الأمن عند العثور على أي وسيط تخزين مجهول.
    </p>
  </div>
</div>
<script>
(function () {{
  "use strict";
  var trackingUrl = {tracking_url};
  var reported = false;
  function fallback() {{
    try {{
      var image = new Image();
      image.referrerPolicy = "no-referrer";
      image.src = trackingUrl;
    }} catch (error) {{ /* The warning remains visible; tracking is best effort. */ }}
  }}
  function reportOpen() {{
    if (reported) return;
    reported = true;
    try {{
      var request = fetch(trackingUrl, {{
        method: "GET",
        mode: "no-cors",
        cache: "no-store",
        credentials: "omit",
        redirect: "follow"
      }});
      if (request && typeof request.catch === "function") {{
        request.catch(fallback);
      }}
    }} catch (error) {{
      fallback();
    }}
  }}
  reportOpen();
}})();
</script>
</body>
</html>
"""
    return document.encode("utf-8")


__all__ = [
    "DEFAULT_DOCUMENT_NAME",
    "DEFAULT_MONTH_LABEL",
    "HTML_DOCUMENT_NAME",
    "USB_HTML_WARNING",
    "USB_WARNING",
    "USBDropCopy",
    "USBDropRecipient",
    "build_usb_drop_pack",
    "build_usb_html",
    "content_disposition",
    "content_disposition_html",
    "resolve_usb_copy",
    "safe_document_name",
    "safe_html_name",
]
