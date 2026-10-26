"""Pydantic v2 schemas for the visual email designer.

The visual editor owns a compact, declarative JSON document.  The backend is
the source of truth for validation and rendering: it accepts the JSON (or the
compiled HTML for legacy templates), sanitises every value, and produces the
table-based HTML that is stored in ``EmailTemplate.body_html`` and sent to
recipients.

The model intentionally uses plain strings for colours/URLs.  Email templates
must be able to contain merge tags such as ``{{tracking_url}}`` which are not
valid absolute URLs until the personalisation step runs.
"""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_FONT_FAMILIES = {
    "Cairo",
    "Tajawal",
    "Segoe UI",
    "Tahoma",
    "Arial",
    "Helvetica",
    "Georgia",
    "Verdana",
    "system-ui",
}


def _validate_color(value: str | None, default: str) -> str:
    """Return a normalised CSS hex colour.

    Args:
        value: Candidate colour from the editor.
        default: Fallback used when ``value`` is empty.

    Returns:
        A six-digit CSS hex colour.

    Raises:
        ValueError: When a non-empty value is not a valid hex colour.
    """
    candidate = (value or "").strip()
    if not candidate:
        return default
    if not _HEX_COLOR_RE.match(candidate):
        raise ValueError("must be a CSS hex colour such as #0F6CBD")
    if len(candidate) == 4:
        candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
    return candidate.upper()


class EmailDesignSettings(BaseModel):
    """Canvas-wide settings for an email design."""

    model_config = ConfigDict(extra="ignore")

    background_color: str = "#F2F4F7"
    content_background_color: str = "#FFFFFF"
    font_family: str = "Cairo"
    text_color: str = "#344054"
    link_color: str = "#0F6CBD"
    width: int = Field(default=600, ge=320, le=900)
    content_padding: int = Field(default=32, ge=8, le=80)
    border_radius: int = Field(default=14, ge=0, le=40)
    preheader: str = Field(default="", max_length=300)

    @field_validator("background_color", "content_background_color", "text_color", "link_color")
    @classmethod
    def _colours(cls, value: str) -> str:
        return _validate_color(value, "#FFFFFF")

    @field_validator("font_family")
    @classmethod
    def _font(cls, value: str) -> str:
        candidate = (value or "Cairo").strip()
        return candidate if candidate in _FONT_FAMILIES else "Cairo"


class _BlockBase(BaseModel):
    """Fields shared by every visual block."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=64)
    padding_top: int = Field(default=0, ge=0, le=120)
    padding_bottom: int = Field(default=12, ge=0, le=120)
    align: Literal["left", "center", "right"] = "right"

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            return uuid.uuid4().hex
        # Keep DOM ids/data attributes predictable and injection-free.
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", candidate)[:64]
        return cleaned or uuid.uuid4().hex


class TextBlock(_BlockBase):
    """A rich-text paragraph."""

    type: Literal["text"] = "text"
    content: str = Field(default="", max_length=50_000)
    font_size: int = Field(default=16, ge=10, le=48)
    color: str | None = None
    font_weight: Literal["normal", "bold"] = "normal"
    line_height: float = Field(default=1.7, ge=1.0, le=3.0)

    @field_validator("color")
    @classmethod
    def _text_colour(cls, value: str | None) -> str | None:
        return _validate_color(value, "#344054") if value else None


class ImageBlock(_BlockBase):
    """A remote image with an optional click target."""

    type: Literal["image"] = "image"
    src: str = Field(default="", max_length=2_000)
    alt: str = Field(default="", max_length=500)
    link: str = Field(default="", max_length=2_000)
    width: int = Field(default=520, ge=40, le=900)
    border_radius: int = Field(default=8, ge=0, le=80)


class ButtonBlock(_BlockBase):
    """A call-to-action button."""

    type: Literal["button"] = "button"
    label: str = Field(default="Open document", max_length=500)
    url: str = Field(default="{{tracking_url}}", max_length=2_000)
    background_color: str = "#0F6CBD"
    text_color: str = "#FFFFFF"
    border_radius: int = Field(default=8, ge=0, le=40)
    font_size: int = Field(default=15, ge=10, le=32)
    padding_x: int = Field(default=28, ge=8, le=80)
    padding_y: int = Field(default=13, ge=6, le=40)

    @field_validator("background_color", "text_color")
    @classmethod
    def _button_colours(cls, value: str) -> str:
        return _validate_color(value, "#0F6CBD")


class DividerBlock(_BlockBase):
    """A horizontal rule."""

    type: Literal["divider"] = "divider"
    color: str = "#EAECF0"
    thickness: int = Field(default=1, ge=1, le=8)
    width_percent: int = Field(default=100, ge=10, le=100)

    @field_validator("color")
    @classmethod
    def _divider_colour(cls, value: str) -> str:
        return _validate_color(value, "#EAECF0")


class SpacerBlock(_BlockBase):
    """Vertical whitespace."""

    type: Literal["spacer"] = "spacer"
    height: int = Field(default=24, ge=4, le=200)


class LogoBlock(_BlockBase):
    """The organization logo, resolved at send time from branding settings."""

    type: Literal["logo"] = "logo"
    width: int = Field(default=150, ge=40, le=320)
    link: str = Field(default="", max_length=2_000)
    alt: str = Field(default="", max_length=500)
    show_company_name: bool = True


class FooterBlock(_BlockBase):
    """A branded footer with company and support details."""

    type: Literal["footer"] = "footer"
    text: str = Field(default="", max_length=2_000)
    show_company_name: bool = True
    show_support_email: bool = True
    show_logo: bool = False
    font_size: int = Field(default=12, ge=9, le=20)
    color: str = "#98A2B3"

    @field_validator("color")
    @classmethod
    def _footer_colour(cls, value: str) -> str:
        return _validate_color(value, "#98A2B3")


class HtmlBlock(_BlockBase):
    """A sanitised HTML fragment for advanced/custom content."""

    type: Literal["html"] = "html"
    html: str = Field(default="", max_length=100_000)


EmailDesignBlock = Annotated[
    TextBlock | ImageBlock | ButtonBlock | DividerBlock | SpacerBlock | LogoBlock | FooterBlock | HtmlBlock,
    Field(discriminator="type"),
]


class EmailDesign(BaseModel):
    """The complete visual design stored alongside the compiled HTML."""

    model_config = ConfigDict(extra="ignore")

    version: int = Field(default=1, ge=1, le=10)
    mode: Literal["blocks", "legacy"] = "blocks"
    settings: EmailDesignSettings = Field(default_factory=EmailDesignSettings)
    blocks: list[EmailDesignBlock] = Field(default_factory=list, max_length=200)
    #: Full HTML document for templates created before the visual editor.
    legacy_html: str | None = Field(default=None, max_length=500_000)

    @model_validator(mode="after")
    def _legacy_requires_html(self) -> "EmailDesign":
        if self.mode == "legacy" and not (self.legacy_html or "").strip():
            raise ValueError("legacy_html is required when mode is 'legacy'")
        return self


__all__ = [
    "ButtonBlock",
    "DividerBlock",
    "EmailDesign",
    "EmailDesignBlock",
    "EmailDesignSettings",
    "FooterBlock",
    "HtmlBlock",
    "ImageBlock",
    "LogoBlock",
    "SpacerBlock",
    "TextBlock",
]
