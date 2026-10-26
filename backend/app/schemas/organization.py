"""Pydantic v2 schemas: organization branding."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class BrandingPublic(BaseModel):
    """Live organization identity used by the visual editor and emails."""

    organization_id: uuid.UUID
    company_name: str
    primary_color: str
    support_email: str | None = None
    logo_url: str | None = None
    has_logo: bool = False
    updated_at: datetime | None = None


class BrandingUpdate(BaseModel):
    """Partial update for the organization's branding tab."""

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    primary_color: str | None = Field(default=None, max_length=7)
    support_email: EmailStr | None = None

    @field_validator("primary_color")
    @classmethod
    def _valid_colour(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        if not candidate:
            return None
        if not _HEX_COLOR_RE.match(candidate):
            raise ValueError("must be a CSS hex colour such as #0F6CBD")
        if len(candidate) == 4:
            candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
        return candidate.upper()

    @field_validator("support_email", mode="before")
    @classmethod
    def _blank_email(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


__all__ = ["BrandingPublic", "BrandingUpdate"]
