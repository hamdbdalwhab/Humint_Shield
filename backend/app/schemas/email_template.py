"""Pydantic v2 schemas: email templates and visual designs."""
from __future__ import annotations

import html
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.email_design import EmailDesign
from app.schemas.sanitization import sanitize_plain_text

#: Hard cap for an SMS body, counted as the delivered plain text including the
#: ``{{link}}`` placeholder (one SMS segment with a short link).
SMS_BODY_MAX_LENGTH = 170

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def sms_body_length(body_html: str | None) -> int:
    """Return the delivered character count of an SMS template body.

    Args:
        body_html: Stored body (plain text wrapped in ``<p>`` by the seeder) or
            already-plain text from an API caller.

    Returns:
        The length of the text after tags are stripped and whitespace collapsed.
    """
    raw = html.unescape(_TAG_RE.sub(" ", body_html or ""))
    return len(_WHITESPACE_RE.sub(" ", raw).strip())


class EmailTemplateBase(BaseModel):
    """Shared template fields."""

    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=500)
    channel: str = Field(default="email", pattern="^(email|sms|whatsapp|qr)$")
    #: ``IT``, ``Finance``, ``HR``, ``Executive`` or ``All`` (None = generic).
    target_department: str | None = Field(default=None, max_length=50)
    difficulty_level: int = Field(default=5, ge=1, le=10)
    is_active: bool = True

    @field_validator("target_department")
    @classmethod
    def _normalise_department(cls, value: str | None) -> str | None:
        """Trim the value and treat ``All``/blank as the generic audience."""
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if clean.lower() == "all":
            return "All"
        return clean[:1].upper() + clean[1:]

    @field_validator("name", "subject", mode="before")
    @classmethod
    def _sanitize_plain_fields(cls, value: object) -> object:
        """Reject active content and strip markup from title/subject.

        ``body_html`` is intentionally excluded: it is compiled and sanitised
        by the template pipeline, which neutralises (rather than rejects)
        scripts so a legitimate design can still be saved and repaired.
        """
        if value is None:
            return value
        cleaned = sanitize_plain_text(str(value), "field")
        return cleaned


class EmailTemplateCreate(EmailTemplateBase):
    """Payload for creating a template.

    A caller may send the compiled ``body_html`` (legacy clients), the visual
    ``design_json`` (new editor), or both.  When ``design_json`` is present the
    backend recompiles and sanitises ``body_html`` so the two can never drift.
    """

    body_html: str | None = Field(default=None, min_length=1)
    design_json: EmailDesign | None = None
    available_variables: list[str] | None = None

    @model_validator(mode="after")
    def _content_required(self) -> "EmailTemplateCreate":
        if not (self.body_html or "").strip() and self.design_json is None:
            raise ValueError("body_html or design_json is required")
        return self

    @model_validator(mode="after")
    def _sms_length(self) -> "EmailTemplateCreate":
        if self.channel == "sms" and self.design_json is None:
            length = sms_body_length(self.body_html)
            if length > SMS_BODY_MAX_LENGTH:
                raise ValueError(
                    f"SMS body is {length} characters; the limit is "
                    f"{SMS_BODY_MAX_LENGTH} including {{{{link}}}}"
                )
        return self


class EmailTemplateUpdate(BaseModel):
    """Partial update payload for a template."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
    design_json: EmailDesign | None = None
    channel: str | None = Field(default=None, pattern="^(email|sms|whatsapp|qr)$")
    target_department: str | None = Field(default=None, max_length=50)
    difficulty_level: int | None = Field(default=None, ge=1, le=10)
    is_active: bool | None = None
    available_variables: list[str] | None = None

    @field_validator("target_department")
    @classmethod
    def _normalise_department(cls, value: str | None) -> str | None:
        """Trim the value and treat ``All``/blank as the generic audience."""
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        return "All" if clean.lower() == "all" else clean[:1].upper() + clean[1:]

    @field_validator("name", "subject", mode="before")
    @classmethod
    def _sanitize_plain_fields(cls, value: object) -> object:
        """Reject active content and strip markup from title/subject."""
        if value is None:
            return value
        return sanitize_plain_text(str(value), "field")

    @model_validator(mode="after")
    def _sms_length(self) -> "EmailTemplateUpdate":
        if self.channel == "sms" and self.body_html is not None and self.design_json is None:
            length = sms_body_length(self.body_html)
            if length > SMS_BODY_MAX_LENGTH:
                raise ValueError(
                    f"SMS body is {length} characters; the limit is "
                    f"{SMS_BODY_MAX_LENGTH} including {{{{link}}}}"
                )
        return self


class EmailTemplatePublic(BaseModel):
    """Template representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    subject: str
    body_html: str
    design_json: dict[str, Any] | None = None
    channel: str = "email"
    target_department: str | None = None
    difficulty_level: int
    available_variables: list[str]
    is_built_in: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("available_variables", mode="before")
    @classmethod
    def _default_variables(cls, value: object) -> object:
        """Guard against NULL ``available_variables`` in legacy rows."""
        if value is None:
            return []
        return value


class TemplatePreviewRequest(BaseModel):
    """Body for ``POST /email-templates/{id}/preview``."""

    employee_id: uuid.UUID


class TemplatePreviewResponse(BaseModel):
    """The rendered preview."""

    subject: str
    html_content: str
    text_content: str | None = None
    missing_variables: list[str] = Field(default_factory=list)


class TemplateTestSendRequest(BaseModel):
    """Body for sending the current, possibly unsaved, design to the admin."""

    subject: str = Field(min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
    design_json: EmailDesign | None = None
    channel: str = Field(default="email", pattern="^(email|sms|whatsapp|qr)$")

    @model_validator(mode="after")
    def _content_required(self) -> "TemplateTestSendRequest":
        if not (self.body_html or "").strip() and self.design_json is None:
            raise ValueError("body_html or design_json is required")
        return self


class TemplateTestSendResponse(BaseModel):
    """Outcome of a test-send request."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    to_email: str
    preview_html: str | None = None


__all__ = [
    "EmailTemplateBase",
    "EmailTemplateCreate",
    "EmailTemplatePublic",
    "EmailTemplateUpdate",
    "TemplatePreviewRequest",
    "TemplatePreviewResponse",
    "TemplateTestSendRequest",
    "TemplateTestSendResponse",
]
