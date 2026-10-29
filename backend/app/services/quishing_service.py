"""Quishing assets: high-resolution QR codes and printable Arabic posters.

The quishing channel is delivered outside an email/SMS provider.  An operator
downloads a PDF poster pack and prints one page per recipient.  Every page
carries a unique, unguessable tracking URL so a scan can be attributed to one
employee without embedding any personal data in the QR code itself.

All Arabic copy is shaped with ``arabic-reshaper`` + ``python-bidi`` before it
is drawn with ReportLab.  The QR code itself is generated with the ``qrcode``
library at print resolution (1200 px) and embedded as a lossless PNG.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

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
QR_PIXELS = 1200
QR_BOX_SIZE = 24
QR_BORDER = 4

_DARK = colors.HexColor("#050A14")
_PANEL = colors.HexColor("#0C1526")
_PANEL_2 = colors.HexColor("#111E33")
_WHITE = colors.HexColor("#F8FAFC")
_MUTED = colors.HexColor("#94A3B8")
_LINE = colors.HexColor("#24344D")
_ACCENT = colors.HexColor("#22D3EE")
_ACCENT_2 = colors.HexColor("#6366F1")

#: Built-in Arabic pretexts.  ``key`` is stored in ``campaigns.channel_config``
#: so an operator can reproduce the exact poster that was used in a campaign.
QR_PRECEPTS: dict[str, dict[str, str]] = {
    "it_security": {
        "label": "تحديث أمني إلزامي",
        "headline": "تحديث أمني مطلوب لحسابك",
        "body": (
            "اكتشف فريق أمن المعلومات نشاطاً غير معتاد على حسابك. "
            "امسح رمز الاستجابة السريعة لتأكيد هويتك وإعادة تفعيل الوصول "
            "خلال 24 ساعة، وإلا سيتم تعليق الحساب مؤقتاً."
        ),
        "footer": "قسم أمن المعلومات — {company}",
    },
    "hr_policy": {
        "label": "سياسة الموارد البشرية",
        "headline": "تحديث سياسة العمل عن بُعد",
        "body": (
            "صدرت نسخة محدثة من سياسة العمل عن بُعد. امسح الرمز للاطلاع على "
            "السياسة الجديدة وتأكيد قراءتك قبل نهاية الأسبوع."
        ),
        "footer": "إدارة الموارد البشرية — {company}",
    },
    "finance_bonus": {
        "label": "إقرار المكافأة الربعية",
        "headline": "إقرار مكافأة الربع الثالث",
        "body": (
            "تم اعتماد مكافأة الربع الثالث. امسح الرمز للتحقق من بياناتك "
            "البنكية وتأكيد استلام المكافأة قبل إغلاق دورة الرواتب."
        ),
        "footer": "الإدارة المالية — {company}",
    },
    "free_coffee": {
        "label": "قهوة مجانية",
        "headline": "قهوة مجانية بانتظارك اليوم",
        "body": (
            "بمناسبة أسبوع الامتنان، تقدّم الكافتيريا مشروباً مجانياً لكل موظف. "
            "امسح الرمز لاستلام قسيمتك قبل الساعة الثالثة عصراً."
        ),
        "footer": "كافتيريا الشركة — {company}",
    },
}
DEFAULT_PRECEPT_KEY = "it_security"


@dataclass(slots=True)
class PosterRecipient:
    """One printed poster recipient and its unique tracking link."""

    name: str
    email: str
    tracking_uuid: str
    tracking_url: str


@dataclass(slots=True)
class PosterCopy:
    """Resolved Arabic poster copy."""

    label: str
    headline: str
    body: str
    footer: str
    pretext_key: str


def _text(value: Any) -> str:
    """Return a stripped string for arbitrary database values."""
    return "" if value is None else str(value).strip()


def resolve_poster_copy(
    channel_config: Mapping[str, Any] | None,
    *,
    company_name: str = "Our Company",
) -> PosterCopy:
    """Resolve the Arabic pretext for a QR campaign.

    The configuration accepts either a nested ``qr`` object or the legacy flat
    keys (``headline``, ``body``, ``footer``, ``pretext_key``).  Explicit values
    always win over the selected built-in pretext.
    """
    config = dict(channel_config or {})
    qr_config = config.get("qr")
    if isinstance(qr_config, Mapping):
        merged: dict[str, Any] = {**config, **dict(qr_config)}
    else:
        merged = config

    key = _text(merged.get("pretext_key")) or DEFAULT_PRECEPT_KEY
    preset = QR_PRECEPTS.get(key, QR_PRECEPTS[DEFAULT_PRECEPT_KEY])
    resolved_key = key if key in QR_PRECEPTS else DEFAULT_PRECEPT_KEY

    headline = _text(merged.get("headline")) or preset["headline"]
    body = _text(merged.get("body")) or preset["body"]
    footer = _text(merged.get("footer")) or preset["footer"]
    label = _text(merged.get("label")) or preset["label"]

    company = _text(company_name) or "Our Company"
    return PosterCopy(
        label=label.format(company=company),
        headline=headline.format(company=company),
        body=body.format(company=company),
        footer=footer.format(company=company),
        pretext_key=resolved_key,
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
    # ``qrcode`` returns an image whose exact size depends on the module count;
    # normalise it to a consistent, high-resolution square without blurring.
    if image.width != QR_PIXELS:
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
) -> float:
    """Draw right-aligned shaped lines and return the next baseline."""
    y = y_top
    pdf.setFillColor(colour)
    pdf.setFont(font, size)
    for line in lines:
        pdf.drawRightString(x_right, y, _visual(line))
        y -= leading
    return y


def _draw_logo(
    pdf: canvas.Canvas,
    logo: bytes | None,
    *,
    x: float,
    y: float,
    max_width: float,
    max_height: float,
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
        pdf.drawImage(
            reader,
            x + (max_width - draw_width) / 2,
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
) -> None:
    """Draw a branded initial tile when no logo is configured."""
    name = _text(company_name) or "H"
    initial = "".join(part[:1] for part in name.split()[:2]).upper()[:2] or "H"
    pdf.setFillColor(_ACCENT)
    pdf.roundRect(x, y, size, size, size * 0.22, fill=1, stroke=0)
    font_regular, font_bold = _fonts()
    pdf.setFillColor(_DARK)
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
    """Draw one A4 poster page."""
    width, height = A4
    font_regular, font_bold = _fonts()
    company = _text(getattr(organization, "name", None)) or "Our Company"
    primary = _text(getattr(organization, "brand_primary_color", None)) or "#0F6CBD"
    try:
        accent = colors.HexColor(primary)
    except Exception:  # pragma: no cover - invalid legacy colour
        accent = _ACCENT

    # Background and ambient brand shapes.
    pdf.setFillColor(_DARK)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setFillColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.10))
    pdf.circle(width + 40, height - 60, 230, fill=1, stroke=0)
    pdf.setFillColor(colors.Color(_ACCENT_2.red, _ACCENT_2.green, _ACCENT_2.blue, alpha=0.08))
    pdf.circle(-50, 120, 190, fill=1, stroke=0)

    margin = 48
    right = width - margin
    left = margin
    content_width = width - 2 * margin

    # Header: logo/brand mark on the right, simulation badge on the left.
    logo = getattr(organization, "brand_logo_data", None)
    if _draw_logo(pdf, logo, x=right - 118, y=height - 120, max_width=118, max_height=52):
        pass
    else:
        _draw_initial_mark(pdf, company, x=right - 48, y=height - 112, size=44)
    pdf.setFillColor(_WHITE)
    pdf.setFont(font_bold, 15)
    pdf.drawRightString(right - 132, height - 96, _visual(company))

    pdf.setFillColor(colors.Color(_ACCENT.red, _ACCENT.green, _ACCENT.blue, alpha=0.14))
    pdf.roundRect(left, height - 112, 152, 28, 14, fill=1, stroke=0)
    pdf.setFillColor(_ACCENT)
    pdf.setFont(font_bold, 8.5)
    pdf.drawCentredString(left + 76, height - 102, _visual("محاكاة تدريبية معتمدة"))

    # Pretext label.
    pdf.setFillColor(accent)
    pdf.setFont(font_bold, 10.5)
    pdf.drawRightString(right, height - 176, _visual(copy.label))
    pdf.setStrokeColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.55))
    pdf.setLineWidth(1)
    pdf.line(right - 230, height - 190, right, height - 190)

    # Headline and body.
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
        y_top=height - 226,
        font=font_bold,
        size=27,
        leading=38,
        colour=_WHITE,
    )
    body_lines = _wrap(
        copy.body,
        font=font_regular,
        size=12.5,
        max_width=content_width - 20,
        max_lines=6,
    )
    y = _draw_rtl_lines(
        pdf,
        body_lines,
        x_right=right,
        y_top=y - 18,
        font=font_regular,
        size=12.5,
        leading=21,
        colour=_MUTED,
    )

    # QR card.
    qr_size = 292
    card_size = qr_size + 38
    card_x = (width - card_size) / 2
    card_y = max(126, y - card_size - 36)
    pdf.setFillColor(_PANEL)
    pdf.roundRect(card_x - 8, card_y - 8, card_size + 16, card_size + 16, 26, fill=1, stroke=0)
    pdf.setStrokeColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.55))
    pdf.setLineWidth(1.2)
    pdf.roundRect(card_x - 8, card_y - 8, card_size + 16, card_size + 16, 26, fill=0, stroke=1)
    pdf.setFillColor(colors.white)
    pdf.roundRect(card_x, card_y, card_size, card_size, 20, fill=1, stroke=0)
    pdf.drawImage(
        ImageReader(io.BytesIO(qr_png)),
        card_x + 19,
        card_y + 19,
        width=qr_size,
        height=qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    # Recipient personalisation below the card.
    name = _text(recipient.name) or _text(recipient.email) or "زميلنا العزيز"
    pdf.setFillColor(_WHITE)
    pdf.setFont(font_bold, 13)
    pdf.drawCentredString(width / 2, card_y - 34, _visual(name))
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 9.5)
    pdf.drawCentredString(
        width / 2,
        card_y - 52,
        _visual("امسح الرمز بهاتف العمل لإكمال التحقق"),
    )

    # Footer.
    pdf.setStrokeColor(_LINE)
    pdf.setLineWidth(0.8)
    pdf.line(left, 84, right, 84)
    pdf.setFillColor(_MUTED)
    pdf.setFont(font_regular, 8.5)
    pdf.drawRightString(right, 66, _visual(copy.footer))
    if support_email:
        pdf.drawString(left, 66, _text(support_email))
    pdf.setFillColor(colors.Color(_MUTED.red, _MUTED.green, _MUTED.blue, alpha=0.75))
    pdf.setFont(font_regular, 7.5)
    pdf.drawCentredString(
        width / 2,
        45,
        _visual(
            "هذه محاكاة تدريبية من HUMINT Shield. لا تُدخل بيانات دخول حقيقية. "
            "أبلغ فريق الأمن إذا اشتبهت في أي رسالة."
        ),
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
    copy = resolve_poster_copy(channel_config, company_name=company)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"{company} — Quishing simulation posters")
    pdf.setAuthor("HUMINT Shield")
    pdf.setSubject(
        f"Authorized security-awareness simulation: {_text(getattr(campaign, 'name', ''))}"
    )

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
    "DEFAULT_PRECEPT_KEY",
    "QR_PRECEPTS",
    "PosterCopy",
    "PosterRecipient",
    "build_poster_pack",
    "generate_qr_png",
    "resolve_poster_copy",
]
