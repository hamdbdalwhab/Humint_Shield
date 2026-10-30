"""Quishing assets: high-resolution QR codes and print-ready Arabic posters.

The quishing channel is delivered outside an email/SMS provider.  An operator
downloads a PDF poster pack and prints one page per recipient.  Every page
carries a unique, unguessable tracking URL so a scan can be attributed to one
employee without embedding any personal data in the QR code itself.

The poster deliberately looks like a genuine internal corporate notice: white
background, the company logo, the company name and department, and copy that
matches the selected lure type.  It contains **no** training/simulation wording
and no product branding.

All Arabic copy is shaped with ``arabic-reshaper`` + ``python-bidi`` before it
is drawn with ReportLab.  The QR code itself is generated with the ``qrcode``
library at print resolution (1200 px) and embedded as a lossless PNG.
"""
from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape  # noqa: F401 - kept for API compatibility

import arabic_reshaper
import qrcode
from bidi.algorithm import get_display
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.services import executive_report

#: Print-ready QR edge length in pixels.  The PDF embeds the PNG at 300 dpi.
#: 400 px is > 300 dpi at the 300 pt print size used by the poster and keeps
#: generation well under one second.
QR_PIXELS = 400
QR_BOX_SIZE = 8
QR_BORDER = 4

_WHITE = colors.HexColor("#FFFFFF")
_PAPER = colors.HexColor("#F7F9FC")
_INK = colors.HexColor("#111827")
_SLATE = colors.HexColor("#4B5563")
_MUTED = colors.HexColor("#6B7280")
_LINE = colors.HexColor("#D7DEE8")
_FALLBACK_PRIMARY = colors.HexColor("#0F6CBD")
_FALLBACK_ACCENT = colors.HexColor("#1F3A5F")

#: Supported lure types.  ``key`` is stored in ``campaigns.channel_config`` so
#: an operator can reproduce the exact poster that was used in a campaign.
QR_LURES: dict[str, dict[str, str]] = {
    "coffee": {
        "label": "مكافأة الموظفين",
        "headline": "قهوة مجانية بانتظارك اليوم",
        "body": (
            "بمناسبة أسبوع الامتنان، تقدّم كافتيريا الشركة مشروباً ساخناً مجاناً "
            "لكل موظف. امسح الرمز لاستلام قسيمتك قبل الساعة الثالثة عصراً."
        ),
        "cta": "امسح الرمز لاستلام القسيمة",
        "footer": "كافتيريا الشركة",
    },
    "bonus": {
        "label": "إدارة الرواتب",
        "headline": "تم اعتماد مكافأة الأداء",
        "body": (
            "يسر الإدارة المالية إبلاغك باعتماد مكافأة الأداء لهذا الربع. امسح "
            "الرمز للتحقق من بياناتك وتأكيد استلام المكافأة قبل إغلاق دورة الرواتب."
        ),
        "cta": "امسح الرمز لتأكيد استلام المكافأة",
        "footer": "الإدارة المالية",
    },
    "nomination": {
        "label": "جوائز الموظف المثالي",
        "headline": "ترشيحك لأفضل موظف",
        "body": (
            "تم ترشيحك ضمن قائمة أفضل الموظفين لشهر {month}. امسح الرمز للاطلاع "
            "على تفاصيل الترشيح وتأكيد قبولك قبل إعلان النتائج."
        ),
        "cta": "امسح الرمز لعرض الترشيح",
        "footer": "إدارة الجوائز والتقدير",
    },
    "hr": {
        "label": "الموارد البشرية",
        "headline": "تحديث بيانات الموظف مطلوب",
        "body": (
            "يتطلب نظام الموارد البشرية تحديث بياناتك الشخصية وبيانات الاتصال. "
            "امسح الرمز لإكمال التحديث قبل نهاية الأسبوع لتجنّب تعليق الخدمات."
        ),
        "cta": "امسح الرمز لتحديث بياناتك",
        "footer": "إدارة الموارد البشرية",
    },
    "wifi": {
        "label": "شبكة الضيوف",
        "headline": "دخول سريع إلى شبكة الشركة",
        "body": (
            "شبكة Wi-Fi للزوار تتطلب تسجيل الدخول مرة واحدة على الأجهزة الجديدة. "
            "امسح الرمز لتفعيل الاتصال بالإنترنت داخل مبنى الإدارة."
        ),
        "cta": "امسح الرمز لتفعيل الاتصال",
        "footer": "إدارة تقنية المعلومات",
    },
}

#: Backwards-compatible alias used by older callers/tests.
QR_PRECEPTS = QR_LURES
DEFAULT_LURE_KEY = "hr"
DEFAULT_PRECEPT_KEY = DEFAULT_LURE_KEY

_LURE_ALIASES = {
    "free_coffee": "coffee",
    "salary_bonus": "bonus",
    "finance_bonus": "bonus",
    "top_employee": "nomination",
    "hr_policy": "hr",
    "hr_update": "hr",
    "it_security": "hr",
    "wifi_access": "wifi",
}

_MONTHS_AR = (
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


@dataclass(slots=True)
class PosterRecipient:
    """One printed poster recipient and its unique tracking link."""

    name: str
    email: str
    tracking_uuid: str
    tracking_url: str


@dataclass(slots=True)
class PosterCopy:
    """Resolved Arabic poster copy and branding."""

    label: str
    headline: str
    body: str
    cta: str
    footer: str
    lure_type: str
    company_name: str
    department: str
    month_label: str
    primary_color: str
    accent_color: str
    logo: bytes | None

    @property
    def pretext_key(self) -> str:
        """Backwards-compatible alias for the lure key."""
        return self.lure_type


def _text(value: Any) -> str:
    """Return a stripped string for arbitrary database values."""
    return "" if value is None else str(value).strip()


def normalize_lure_type(value: Any) -> str:
    """Return a supported lure key for arbitrary operator input."""
    key = _text(value).strip().lower()
    key = _LURE_ALIASES.get(key, key)
    return key if key in QR_LURES else DEFAULT_LURE_KEY


def _month_label(value: Any) -> str:
    """Return a human month label (``2026-05`` -> ``مايو 2026``)."""
    raw = _text(value)
    if not raw:
        now = datetime.utcnow()
        return f"{_MONTHS_AR[now.month - 1]} {now.year}"
    cleaned = raw.replace("/", "-")
    for fmt in ("%Y-%m", "%m-%Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return f"{_MONTHS_AR[parsed.month - 1]} {parsed.year}"
        except ValueError:
            continue
    return raw


def _decode_logo(value: Any) -> bytes | None:
    """Decode a ``data:image/...;base64,...`` logo or a raw base64 payload."""
    raw = _text(value)
    if not raw:
        return None
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data if data else None


def resolve_poster_copy(
    channel_config: Mapping[str, Any] | None,
    *,
    company_name: str = "Our Company",
    department: str = "",
    primary_color: str = "",
    accent_color: str = "",
    logo: bytes | None = None,
) -> PosterCopy:
    """Resolve the poster copy, branding and lure type for a QR campaign.

    The configuration accepts a nested ``qr`` object (preferred) or legacy flat
    keys (``pretext_key``, ``headline``, ``body``, ``footer``, ``label``).
    Explicit values always win over the selected built-in lure.
    """
    config = dict(channel_config or {})
    qr_config = config.get("qr")
    if isinstance(qr_config, Mapping):
        merged: dict[str, Any] = {**config, **dict(qr_config)}
    else:
        merged = config

    lure_type = normalize_lure_type(
        merged.get("lure_type") or merged.get("pretext_key")
    )
    preset = QR_LURES[lure_type]

    company = _text(merged.get("company_name")) or _text(company_name) or "Our Company"
    dept = _text(merged.get("department")) or _text(department)
    month = _month_label(merged.get("month_label") or merged.get("nomination_month"))

    def _resolve(field: str) -> str:
        value = _text(merged.get(field)) or preset[field]
        return value.format(company=company, department=dept, month=month)

    logo_bytes = _decode_logo(merged.get("logo_data_url")) or logo
    return PosterCopy(
        label=_resolve("label"),
        headline=_resolve("headline"),
        body=_resolve("body"),
        cta=_resolve("cta"),
        footer=_resolve("footer") or dept or company,
        lure_type=lure_type,
        company_name=company,
        department=dept,
        month_label=month if lure_type == "nomination" else "",
        primary_color=_text(merged.get("primary_color")) or _text(primary_color) or "#0F6CBD",
        accent_color=_text(merged.get("accent_color")) or _text(accent_color) or "#1F3A5F",
        logo=logo_bytes,
    )


def generate_qr_png(
    data: str,
    *,
    dark: str = "#050A14",
    light: str = "#FFFFFF",
) -> bytes:
    """Render a high-resolution PNG QR code.

    Args:
        data: URL or text encoded in the QR.
        dark: Foreground colour.
        light: Background colour.

    Returns:
        PNG bytes with a quiet zone suitable for print.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=QR_BOX_SIZE,
        border=QR_BORDER,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color=dark, back_color=light).convert("RGB")
    if image.width > QR_PIXELS:
        image = image.resize((QR_PIXELS, QR_PIXELS), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _fonts() -> tuple[str, str]:
    """Return the registered Arabic regular/bold font names."""
    executive_report._register_fonts()  # noqa: SLF001 - shared bundled font
    return executive_report._FONT_REGULAR, executive_report._FONT_BOLD  # noqa: SLF001


def _visual(value: Any) -> str:
    """Return a shaped visual-order string for ReportLab."""
    text = _text(value)
    if not text:
        return ""
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:  # pragma: no cover - shaping is best effort
        return text


def _wrap(
    value: Any,
    *,
    font: str,
    size: float,
    max_width: float,
    max_lines: int | None = None,
) -> list[str]:
    """Wrap text into visual-order lines that fit ``max_width``."""
    words = _text(value).split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and pdfmetrics.stringWidth(_visual(candidate), font, size) > max_width:
            lines.append(" ".join(current))
            current = [word]
            if max_lines is not None and len(lines) >= max_lines:
                break
        else:
            current.append(word)
    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(" ".join(current))
    return lines


def _draw_rtl_lines(
    pdf: canvas.Canvas,
    lines: Iterable[str],
    *,
    x_right: float,
    y_top: float,
    font: str,
    size: float,
    leading: float,
    colour: colors.Color,
    align: str = "right",
) -> float:
    """Draw shaped lines and return the next baseline."""
    y = y_top
    pdf.setFillColor(colour)
    pdf.setFont(font, size)
    for line in lines:
        visual = _visual(line)
        if align == "center":
            pdf.drawCentredString(x_right, y, visual)
        else:
            pdf.drawRightString(x_right, y, visual)
        y -= leading
    return y


def _hex(value: str, fallback: colors.Color) -> colors.Color:
    """Parse a hex colour with a safe fallback."""
    try:
        return colors.HexColor(_text(value))
    except Exception:  # pragma: no cover - invalid operator colour
        return fallback


def _draw_logo(
    pdf: canvas.Canvas,
    logo: bytes | None,
    *,
    x: float,
    y: float,
    max_width: float,
    max_height: float,
    align: str = "right",
) -> bool:
    """Draw an organization logo inside the given box, preserving aspect."""
    if not logo:
        return False
    try:
        reader = ImageReader(io.BytesIO(logo))
        width, height = reader.getSize()
        if not width or not height:
            return False
        scale = min(max_width / width, max_height / height)
        draw_width = width * scale
        draw_height = height * scale
        if align == "right":
            draw_x = x + max_width - draw_width
        elif align == "center":
            draw_x = x + (max_width - draw_width) / 2
        else:
            draw_x = x
        pdf.drawImage(
            reader,
            draw_x,
            y + (max_height - draw_height) / 2,
            width=draw_width,
            height=draw_height,
            mask="auto",
            preserveAspectRatio=True,
        )
        return True
    except Exception:  # pragma: no cover - a corrupt logo must not break print
        return False


def _draw_initial_mark(
    pdf: canvas.Canvas,
    company_name: str,
    *,
    x: float,
    y: float,
    size: float,
    primary: colors.Color = _FALLBACK_PRIMARY,
) -> None:
    """Draw a branded initial tile when no logo is configured."""
    name = _text(company_name) or "C"
    initial = "".join(part[:1] for part in name.split()[:2]).upper()[:2] or "C"
    pdf.setFillColor(primary)
    pdf.roundRect(x, y, size, size, size * 0.22, fill=1, stroke=0)
    font_regular, font_bold = _fonts()
    pdf.setFillColor(_WHITE)
    pdf.setFont(font_bold, size * 0.42)
    pdf.drawCentredString(x + size / 2, y + size * 0.34, initial)


def _draw_poster(
    pdf: canvas.Canvas,
    *,
    organization: Any,
    campaign: Any,
    recipient: PosterRecipient,
    copy: PosterCopy,
    qr_png: bytes,
    support_email: str | None,
) -> None:
    """Draw one pristine, print-ready A4 poster page."""
    width, height = A4
    font_regular, font_bold = _fonts()
    primary = _hex(copy.primary_color, _FALLBACK_PRIMARY)
    accent = _hex(copy.accent_color, _FALLBACK_ACCENT)
    company = copy.company_name

    # White paper background with a discreet brand rule at the top.
    pdf.setFillColor(_WHITE)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(primary)
    pdf.rect(0, height - 10, width, 10, fill=1, stroke=0)

    margin = 54
    right = width - margin
    left = margin
    content_width = width - 2 * margin

    # Header: logo on the right, company name and department underneath.
    logo_drawn = _draw_logo(
        pdf,
        copy.logo,
        x=right - 132,
        y=height - 96,
        max_width=132,
        max_height=58,
        align="right",
    )
    if not logo_drawn:
        _draw_initial_mark(
            pdf, company, x=right - 52, y=height - 92, size=46, primary=primary
        )
    name_x = right - 148 if logo_drawn else right - 66
    pdf.setFillColor(_INK)
    pdf.setFont(font_bold, 15.5)
    pdf.drawRightString(name_x, height - 66, _visual(company))
    subtitle = copy.department or copy.footer
    if subtitle:
        pdf.setFillColor(_MUTED)
        pdf.setFont(font_regular, 9.5)
        pdf.drawRightString(name_x, height - 82, _visual(subtitle))

    # Thin header divider.
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.9)
    pdf.line(left, height - 112, right, height - 112)

    # Lure label pill (right aligned).
    label_font_size = 10
    label_width = pdfmetrics.stringWidth(_visual(copy.label), font_bold, label_font_size) + 34
    label_width = min(label_width, content_width)
    pill_x = right - label_width
    pdf.setFillColor(colors.Color(primary.red, primary.green, primary.blue, alpha=0.12))
    pdf.roundRect(pill_x, height - 150, label_width, 26, 13, fill=1, stroke=0)
    pdf.setFillColor(primary)
    pdf.setFont(font_bold, label_font_size)
    pdf.drawCentredString(pill_x + label_width / 2, height - 142, _visual(copy.label))

    # Month badge for the "Top employee nomination" lure.
    if copy.month_label:
        month_font_size = 9.5
        month_text = _visual(copy.month_label)
        month_width = pdfmetrics.stringWidth(month_text, font_bold, month_font_size) + 26
        pdf.setFillColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.10))
        pdf.roundRect(left, height - 150, month_width, 26, 13, fill=1, stroke=0)
        pdf.setFillColor(accent)
        pdf.setFont(font_bold, month_font_size)
        pdf.drawCentredString(left + month_width / 2, height - 142, month_text)

    # Headline.
    headline_lines = _wrap(
        copy.headline,
        font=font_bold,
        size=27,
        max_width=content_width,
        max_lines=3,
    )
    y = _draw_rtl_lines(
        pdf,
        headline_lines,
        x_right=right,
        y_top=height - 198,
        font=font_bold,
        size=27,
        leading=37,
        colour=_INK,
    )

    # Body copy.
    body_lines = _wrap(
        copy.body,
        font=font_regular,
        size=12.5,
        max_width=content_width - 12,
        max_lines=6,
    )
    y = _draw_rtl_lines(
        pdf,
        body_lines,
        x_right=right,
        y_top=y - 16,
        font=font_regular,
        size=12.5,
        leading=21,
        colour=_SLATE,
    )

    # QR card: white card with a thin border, centred on the page.
    qr_size = 300
    card_size = qr_size + 36
    card_x = (width - card_size) / 2
    card_y = max(120, y - card_size - 30)
    pdf.setFillColor(_PAPER)
    pdf.roundRect(card_x - 10, card_y - 10, card_size + 20, card_size + 20, 18, fill=1, stroke=0)
    pdf.setFillColor(_WHITE)
    pdf.roundRect(card_x, card_y, card_size, card_size, 14, fill=1, stroke=0)
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(1)
    pdf.roundRect(card_x, card_y, card_size, card_size, 14, fill=0, stroke=1)
    pdf.drawImage(
        ImageReader(io.BytesIO(qr_png)),
        card_x + 18,
        card_y + 18,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    # Call to action under the card.
    pdf.setFillColor(primary)
    pdf.setFont(font_bold, 13)
    pdf.drawCentredString(width / 2, card_y - 34, _visual(copy.cta))
    if recipient.name:
        pdf.setFillColor(_MUTED)
        pdf.setFont(font_regular, 9.5)
        pdf.drawCentredString(width / 2, card_y - 52, _visual(recipient.name))

    # Footer: department, company and optional support address only.
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.8)
    pdf.line(left, 82, right, 82)
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 8.5)
    footer_text = copy.footer if copy.footer == company else f"{copy.footer} — {company}"
    pdf.drawRightString(right, 64, _visual(footer_text))
    if support_email:
        pdf.drawString(left, 64, _text(support_email))
    pdf.setFillColor(colors.Color(_MUTED.red, _MUTED.green, _MUTED.blue, alpha=0.85))
    pdf.setFont(font_regular, 7.5)
    pdf.drawCentredString(
        width / 2,
        44,
        _visual("امسح الرمز بكاميرا هاتف العمل. لا تشارك بيانات الدخول مع أي شخص."),
    )
    pdf.showPage()


def build_poster_pack(
    *,
    organization: Any,
    campaign: Any,
    recipients: Iterable[PosterRecipient],
    channel_config: Mapping[str, Any] | None = None,
    support_email: str | None = None,
) -> bytes:
    """Build a multi-page A4 PDF poster pack, one page per recipient.

    Args:
        organization: Organization ORM object (name, colour, logo).
        campaign: Campaign ORM object (used for the PDF title metadata).
        recipients: Recipients with unique tracking URLs.
        channel_config: Campaign ``channel_config`` JSON.
        support_email: Optional support address printed in the footer.

    Returns:
        PDF bytes.  The document contains one page per recipient.
    """
    company = _text(getattr(organization, "name", None)) or "Our Company"
    copy = resolve_poster_copy(
        channel_config,
        company_name=company,
        department=_text(getattr(organization, "department", "")),
        primary_color=_text(getattr(organization, "brand_primary_color", "")),
        accent_color=_text(getattr(organization, "brand_secondary_color", "")),
        logo=getattr(organization, "brand_logo_data", None),
    )
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    # Neutral metadata: the document must look like an internal corporate notice.
    pdf.setTitle(f"{copy.company_name} — {copy.headline}")
    pdf.setAuthor(copy.company_name)
    pdf.setSubject(copy.footer)
    pdf.setCreator(copy.company_name)

    generated = 0
    for recipient in recipients:
        qr_png = generate_qr_png(recipient.tracking_url)
        _draw_poster(
            pdf,
            organization=organization,
            campaign=campaign,
            recipient=recipient,
            copy=copy,
            qr_png=qr_png,
            support_email=support_email,
        )
        generated += 1
    if generated == 0:
        raise ValueError("at least one poster recipient is required")
    pdf.save()
    return buffer.getvalue()


__all__ = [
    "DEFAULT_LURE_KEY",
    "DEFAULT_PRECEPT_KEY",
    "QR_LURES",
    "QR_PRECEPTS",
    "PosterCopy",
    "PosterRecipient",
    "build_poster_pack",
    "generate_qr_png",
    "normalize_lure_type",
    "resolve_poster_copy",
]
