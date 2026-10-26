"""Visual email design rendering and branding injection.

The editor stores a compact JSON document (see
:mod:`app.schemas.email_design`).  This service turns that document into
email-client-safe, table-based HTML, injects the organization's live branding,
and sanitises the result.

Legacy templates (the thirteen built-ins and any custom HTML created before the
visual editor) are represented as ``mode="legacy"`` documents.  They keep their
original full HTML document and remain editable in the visual editor through a
contenteditable iframe.
"""
from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.schemas.email_design import (
    ButtonBlock,
    DividerBlock,
    EmailDesign,
    EmailDesignSettings,
    FooterBlock,
    HtmlBlock,
    ImageBlock,
    LogoBlock,
    SpacerBlock,
    TextBlock,
)
from app.services.html_sanitizer import sanitize_email_html

DEFAULT_PRIMARY_COLOR = "#0F6CBD"
FONT_STACKS = {
    "Cairo": "'Cairo','Tajawal','Segoe UI',Tahoma,Arial,sans-serif",
    "Tajawal": "'Tajawal','Cairo','Segoe UI',Tahoma,Arial,sans-serif",
    "Segoe UI": "'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
    "Tahoma": "Tahoma,Arial,sans-serif",
    "Arial": "Arial,Helvetica,sans-serif",
    "Helvetica": "Helvetica,Arial,sans-serif",
    "Georgia": "Georgia,'Times New Roman',serif",
    "Verdana": "Verdana,Geneva,sans-serif",
    "system-ui": "system-ui,-apple-system,'Segoe UI',sans-serif",
}
MERGE_TAG_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass(slots=True)
class BrandingContext:
    """The live branding values injected into a design at render time."""

    company_name: str = "Our Company"
    primary_color: str = DEFAULT_PRIMARY_COLOR
    support_email: str | None = None
    logo_url: str | None = None

    @property
    def initial(self) -> str:
        """Return a one/two-letter fallback mark for a missing logo."""
        name = (self.company_name or "H").strip()
        parts = [part for part in re.split(r"\s+", name) if part]
        if len(parts) >= 2:
            return (parts[0][:1] + parts[1][:1]).upper()
        return name[:2].upper() or "H"


def branding_from_organization(organization: Any, base_url: str) -> BrandingContext:
    """Build a :class:`BrandingContext` from an organization row.

    Args:
        organization: Organization ORM object (or any object with the same
            attributes).
        base_url: Public application base URL.

    Returns:
        Branding values ready for rendering.
    """
    company = getattr(organization, "name", None) or "Our Company"
    primary = getattr(organization, "brand_primary_color", None) or DEFAULT_PRIMARY_COLOR
    support = getattr(organization, "brand_support_email", None)
    logo_url = logo_url_for_organization(organization, base_url)
    return BrandingContext(
        company_name=company,
        primary_color=primary,
        support_email=support,
        logo_url=logo_url,
    )


def logo_url_for_organization(organization: Any, base_url: str) -> str | None:
    """Return the public logo URL for an organization when a logo exists.

    Args:
        organization: Organization ORM object.
        base_url: Public application base URL.

    Returns:
        An absolute URL with a cache-busting version, or ``None``.
    """
    if not getattr(organization, "brand_logo_data", None):
        return None
    updated = getattr(organization, "brand_logo_updated_at", None)
    version = ""
    if isinstance(updated, datetime):
        version = f"?v={int(updated.timestamp())}"
    return (
        f"{base_url.rstrip('/')}/api/v1/public/branding/"
        f"{getattr(organization, 'id', '')}/logo{version}"
    )


def _escape(value: Any) -> str:
    """Escape a value for HTML text/attributes."""
    return html.escape(str(value or ""), quote=True)


def _font_stack(settings: EmailDesignSettings) -> str:
    """Return a safe CSS font stack for the selected family."""
    return FONT_STACKS.get(settings.font_family, FONT_STACKS["Cairo"])


def _logo_markup(branding: BrandingContext, *, width: int, alt: str = "") -> str:
    """Render the organization logo, or a branded initial fallback."""
    label = _escape(alt or branding.company_name)
    if branding.logo_url:
        return (
            f'<img src="{_escape(branding.logo_url)}" alt="{label}" width="{width}" '
            'style="display:inline-block;max-width:100%;height:auto;border:0;outline:none;" />'
        )
    return (
        f'<span style="display:inline-block;width:{width}px;height:{width}px;line-height:'
        f'{width}px;border-radius:14px;background:{_escape(branding.primary_color)};'
        f'color:#ffffff;text-align:center;font-size:{max(12, width // 3)}px;'
        'font-weight:800;letter-spacing:.5px;">'
        f"{_escape(branding.initial)}</span>"
    )


def _padding(block: Any) -> str:
    """Return a safe vertical padding declaration for a block."""
    return f"padding-top:{int(block.padding_top)}px;padding-bottom:{int(block.padding_bottom)}px;"


def _render_text(block: TextBlock, settings: EmailDesignSettings) -> str:
    """Render a rich-text block."""
    colour = block.color or settings.text_color
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" data-hs-editable="text" '
        'class="hs-email-text" '
        f'style="{_padding(block)}text-align:{block.align};font-size:{block.font_size}px;'
        f'line-height:{block.line_height};color:{_escape(colour)};'
        f'font-weight:{block.font_weight};">{block.content}</div>'
    )


def _render_image(block: ImageBlock, settings: EmailDesignSettings) -> str:
    """Render an image block (with an optional tracked link)."""
    if not (block.src or "").strip():
        return (
            f'<div data-hs-block-id="{_escape(block.id)}" style="{_padding(block)}'
            'text-align:center;color:#98A2B3;font-size:13px;">'
            "Image</div>"
        )
    image = (
        f'<img src="{_escape(block.src)}" alt="{_escape(block.alt)}" width="{block.width}" '
        'style="display:inline-block;max-width:100%;height:auto;border:0;outline:none;'
        f'border-radius:{block.border_radius}px;" />'
    )
    if (block.link or "").strip():
        image = (
            f'<a href="{_escape(block.link)}" target="_blank" rel="noopener noreferrer" '
            'style="text-decoration:none;">'
            f"{image}</a>"
        )
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" style="{_padding(block)}'
        f'text-align:{block.align};">{image}</div>'
    )


def _render_button(block: ButtonBlock, settings: EmailDesignSettings) -> str:
    """Render an email-safe call-to-action button."""
    label = _escape(block.label)
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" style="{_padding(block)}'
        f'text-align:{block.align};">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="display:inline-table;border-collapse:separate;"><tr>'
        f'<td bgcolor="{_escape(block.background_color)}" '
        f'style="border-radius:{block.border_radius}px;">'
        f'<a data-hs-editable="button" href="{_escape(block.url)}" target="_blank" '
        'rel="noopener noreferrer" style="display:inline-block;'
        f'padding:{block.padding_y}px {block.padding_x}px;font-family:{_font_stack(settings)};'
        f'font-size:{block.font_size}px;font-weight:700;color:{_escape(block.text_color)};'
        f'text-decoration:none;border-radius:{block.border_radius}px;">{label}</a>'
        "</td></tr></table></div>"
    )


def _render_divider(block: DividerBlock, settings: EmailDesignSettings) -> str:
    """Render a horizontal divider."""
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" style="{_padding(block)}'
        'text-align:center;">'
        f'<div style="display:inline-block;width:{block.width_percent}%;'
        f'border-top:{block.thickness}px solid {_escape(block.color)};'
        'font-size:0;line-height:0;">&nbsp;</div></div>'
    )


def _render_spacer(block: SpacerBlock, settings: EmailDesignSettings) -> str:
    """Render vertical whitespace."""
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" aria-hidden="true" '
        f'style="height:{block.height}px;line-height:{block.height}px;font-size:0;">'
        "&nbsp;</div>"
    )


def _render_logo(block: LogoBlock, settings: EmailDesignSettings, branding: BrandingContext) -> str:
    """Render the organization logo block."""
    logo = _logo_markup(branding, width=block.width, alt=block.alt or branding.company_name)
    if (block.link or "").strip():
        logo = (
            f'<a href="{_escape(block.link)}" target="_blank" rel="noopener noreferrer" '
            'style="text-decoration:none;">'
            f"{logo}</a>"
        )
    company = ""
    if block.show_company_name:
        company = (
            f'<div style="font-size:13px;font-weight:800;color:{_escape(branding.primary_color)};'
            f'margin-top:8px;">{_escape(branding.company_name)}</div>'
        )
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" style="{_padding(block)}'
        f'text-align:{block.align};">{logo}{company}</div>'
    )


def _render_footer(block: FooterBlock, settings: EmailDesignSettings, branding: BrandingContext) -> str:
    """Render the branded footer."""
    parts: list[str] = []
    if block.show_logo:
        parts.append(
            f'<div style="margin-bottom:12px;">'
            f"{_logo_markup(branding, width=42, alt=branding.company_name)}</div>"
        )
    if block.show_company_name:
        parts.append(
            f'<div style="font-weight:700;color:#667085;">{_escape(branding.company_name)}</div>'
        )
    if block.text.strip():
        parts.append(
            f'<div style="margin-top:6px;">{_escape(block.text).replace(chr(10), "<br />")}</div>'
        )
    if block.show_support_email and branding.support_email:
        parts.append(
            '<div style="margin-top:6px;">'
            f'<a href="mailto:{_escape(branding.support_email)}" '
            f'style="color:{_escape(settings.link_color)};text-decoration:none;">'
            f"{_escape(branding.support_email)}</a></div>"
        )
    parts.append(
        f'<div style="margin-top:10px;font-size:11px;">&copy; {datetime.now(timezone.utc).year} '
        f"{_escape(branding.company_name)}. All rights reserved.</div>"
    )
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" class="hs-email-footer" '
        f'style="{_padding(block)}text-align:{block.align};font-size:{block.font_size}px;'
        f'line-height:1.7;color:{_escape(block.color)};">{"".join(parts)}</div>'
    )


def _render_html(block: HtmlBlock, settings: EmailDesignSettings) -> str:
    """Render an advanced HTML fragment."""
    return (
        f'<div data-hs-block-id="{_escape(block.id)}" data-hs-editable="html" '
        f'style="{_padding(block)}">{block.html}</div>'
    )


def _render_block(block: Any, settings: EmailDesignSettings, branding: BrandingContext) -> str:
    """Dispatch a block to its renderer."""
    if isinstance(block, TextBlock):
        return _render_text(block, settings)
    if isinstance(block, ImageBlock):
        return _render_image(block, settings)
    if isinstance(block, ButtonBlock):
        return _render_button(block, settings)
    if isinstance(block, DividerBlock):
        return _render_divider(block, settings)
    if isinstance(block, SpacerBlock):
        return _render_spacer(block, settings)
    if isinstance(block, LogoBlock):
        return _render_logo(block, settings, branding)
    if isinstance(block, FooterBlock):
        return _render_footer(block, settings, branding)
    if isinstance(block, HtmlBlock):
        return _render_html(block, settings)
    return ""


def _shell(
    content: str,
    settings: EmailDesignSettings,
    branding: BrandingContext,
) -> str:
    """Wrap rendered blocks in the responsive email shell."""
    font = _font_stack(settings)
    preheader = _escape(settings.preheader or f"A message from {branding.company_name}")
    return (
        "<!DOCTYPE html>"
        '<html lang="ar" dir="rtl">'
        "<head>"
        '<meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width,initial-scale=1" />'
        '<meta name="color-scheme" content="light dark" />'
        '<meta name="supported-color-schemes" content="light dark" />'
        f"<title>{_escape(branding.company_name)}</title>"
        "<style type=\"text/css\">"
        "html,body{margin:0;padding:0;}"
        "img{border:0;outline:none;text-decoration:none;}"
        "a{text-decoration:none;}"
        "@media only screen and (max-width:620px){"
        ".hs-email-card{width:100% !important;max-width:100% !important;}"
        ".hs-email-pad{padding-left:20px !important;padding-right:20px !important;}"
        "}"
        "@media (prefers-color-scheme:dark){"
        ".hs-email-body{background-color:#0B1220 !important;}"
        ".hs-email-card{background-color:#111A2B !important;border-color:#26364F !important;}"
        ".hs-email-text,.hs-email-footer{color:#E6EDF7 !important;}"
        "}"
        "</style>"
        "</head>"
        f'<body class="hs-email-body" style="margin:0;padding:0;background:{_escape(settings.background_color)};'
        f'font-family:{font};color:{_escape(settings.text_color)};">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">'
        f"{preheader}</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{_escape(settings.background_color)};padding:28px 12px;">'
        '<tr><td align="center">'
        f'<table role="presentation" width="{settings.width}" cellpadding="0" cellspacing="0" '
        f'border="0" class="hs-email-card" style="width:{settings.width}px;max-width:{settings.width}px;'
        f'background:{_escape(settings.content_background_color)};border:1px solid #E4E7EC;'
        f'border-radius:{settings.border_radius}px;overflow:hidden;font-family:{font};">'
        f'<tr><td style="height:4px;background:{_escape(settings.link_color)};font-size:0;'
        'line-height:0;">&nbsp;</td></tr>'
        f'<tr><td class="hs-email-pad" style="padding:{settings.content_padding}px;'
        f'font-family:{font};color:{_escape(settings.text_color)};">{content}</td></tr>'
        "</table>"
        '<div style="max-width:600px;padding:14px 8px 0;font-size:11px;line-height:1.5;'
        f'color:#98A2B3;text-align:center;font-family:{font};">'
        f"{_escape(branding.company_name)} &middot; Security awareness simulation"
        "</div></td></tr></table></body></html>"
    )


def render_email_design(design: EmailDesign, branding: BrandingContext) -> str:
    """Render a validated design to full email HTML.

    Args:
        design: Visual design document.
        branding: Live organization branding.

    Returns:
        Sanitised HTML ready to store or personalise.
    """
    if design.mode == "legacy":
        body = design.legacy_html or ""
        if not re.search(r"<html[\s>]", body, re.IGNORECASE):
            body = _shell(body, design.settings, branding)
        rendered = apply_branding_placeholders(body, branding)
        return sanitize_email_html(rendered)

    blocks_html = "".join(
        _render_block(block, design.settings, branding) for block in design.blocks
    )
    rendered = _shell(blocks_html, design.settings, branding)
    rendered = apply_branding_placeholders(rendered, branding)
    return sanitize_email_html(rendered)


def apply_branding_placeholders(html_text: str, branding: BrandingContext) -> str:
    """Replace branding placeholders in a template.

    Supports ``[LOGO]``, ``[COMPANY_NAME]``, ``[SUPPORT_EMAIL]``,
    ``[PRIMARY_COLOR]`` and ``[YEAR]``.  The replacements are escaped except for
    the logo, which is a fixed image/initial markup string.

    Args:
        html_text: Template HTML.
        branding: Branding values.

    Returns:
        HTML with placeholders resolved.
    """
    if not html_text:
        return ""
    logo = _logo_markup(branding, width=150, alt=branding.company_name)
    support = ""
    if branding.support_email:
        support = (
            f'<a href="mailto:{_escape(branding.support_email)}" '
            f'style="color:{_escape(branding.primary_color)};text-decoration:none;">'
            f"{_escape(branding.support_email)}</a>"
        )
    replacements = {
        "[LOGO]": logo,
        "[COMPANY_NAME]": _escape(branding.company_name),
        "[SUPPORT_EMAIL]": support or _escape(branding.support_email or ""),
        "[PRIMARY_COLOR]": _escape(branding.primary_color),
        "[YEAR]": str(datetime.now(timezone.utc).year),
    }
    rendered = html_text
    for token, value in replacements.items():
        rendered = re.sub(re.escape(token), lambda _m, v=value: v, rendered, flags=re.IGNORECASE)
    return rendered


def default_design(branding: BrandingContext) -> EmailDesign:
    """Create the starter design inherited by every new template.

    The design already contains the organization's logo, primary button colour,
    and a branded footer.  Administrators can change any of it in the editor.

    Args:
        branding: Live organization branding.

    Returns:
        A ready-to-edit visual design.
    """
    primary = branding.primary_color or DEFAULT_PRIMARY_COLOR
    return EmailDesign(
        mode="blocks",
        settings=EmailDesignSettings(
            link_color=primary,
            text_color="#344054",
            background_color="#F2F4F7",
            content_background_color="#FFFFFF",
            font_family="Cairo",
        ),
        blocks=[
            LogoBlock(id=uuid.uuid4().hex, align="right", width=150, padding_top=8, padding_bottom=20),
            TextBlock(
                id=uuid.uuid4().hex,
                content=(
                    "<p style=\"margin:0 0 14px;\">مرحباً {{first_name}}،</p>"
                    "<p style=\"margin:0 0 14px;\">لديك مستند جديد يحتاج مراجعتك قبل نهاية اليوم.</p>"
                ),
                align="right",
                font_size=16,
                padding_bottom=8,
            ),
            ButtonBlock(
                id=uuid.uuid4().hex,
                label="فتح المستند",
                url="{{tracking_url}}",
                background_color=primary,
                align="right",
                padding_top=10,
                padding_bottom=18,
            ),
            TextBlock(
                id=uuid.uuid4().hex,
                content="<p style=\"margin:0;\">شكراً،<br /><strong>{{company_name}}</strong></p>",
                align="right",
                font_size=15,
                padding_bottom=8,
            ),
            FooterBlock(
                id=uuid.uuid4().hex,
                text="رسالة خدمية أُرسلت إلى {{email}}.",
                show_company_name=True,
                show_support_email=True,
                show_logo=False,
                align="right",
                padding_top=18,
                padding_bottom=4,
            ),
        ],
    )


def legacy_design_payload(body_html: str, *, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict[str, Any]:
    """Wrap legacy HTML in a design document.

    Args:
        body_html: Existing compiled HTML.
        primary_color: Organization primary colour for the wrapper settings.

    Returns:
        A JSON-serialisable ``mode="legacy"`` design.
    """
    return EmailDesign(
        mode="legacy",
        settings=EmailDesignSettings(link_color=primary_color),
        legacy_html=body_html or "",
    ).model_dump(mode="json")


def design_for_template(template: Any, *, primary_color: str = DEFAULT_PRIMARY_COLOR) -> EmailDesign:
    """Return a validated design for a stored template.

    Templates created before the visual editor are wrapped lazily so they open
    in the editor without a migration.

    Args:
        template: EmailTemplate ORM object.
        primary_color: Fallback primary colour for legacy wrappers.

    Returns:
        A validated :class:`EmailDesign`.
    """
    raw = getattr(template, "design_json", None)
    if isinstance(raw, dict):
        try:
            return EmailDesign.model_validate(raw)
        except Exception:  # noqa: BLE001 - corrupt JSON must not break the API
            pass
    return EmailDesign(
        mode="legacy",
        settings=EmailDesignSettings(link_color=primary_color),
        legacy_html=getattr(template, "body_html", "") or "",
    )


def compile_design_html(design: EmailDesign, branding: BrandingContext) -> str:
    """Compile and sanitise a design for storage in ``body_html``.

    Args:
        design: Visual design.
        branding: Organization branding.

    Returns:
        Sanitised full HTML.
    """
    return render_email_design(design, branding)


__all__ = [
    "BrandingContext",
    "DEFAULT_PRIMARY_COLOR",
    "apply_branding_placeholders",
    "branding_from_organization",
    "compile_design_html",
    "default_design",
    "design_for_template",
    "legacy_design_payload",
    "logo_url_for_organization",
    "render_email_design",
]
