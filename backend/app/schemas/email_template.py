"""Pydantic v2 schemas: email templates and visual designs."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.email_design import EmailDesign


class EmailTemplateBase(BaseModel):
    """Shared template fields."""

    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=500)
    channel: str = Field(default="email", pattern="^(email|sms|whatsapp|qr)$")
    difficulty_level: int = Field(default=5, ge=1, le=10)
    is_active: bool = True


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


class EmailTemplateUpdate(BaseModel):
    """Partial update payload for a template."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
    design_json: EmailDesign | None = None
    channel: str | None = Field(default=None, pattern="^(email|sms|whatsapp|qr)$")
    difficulty_level: int | None = Field(default=None, ge=1, le=10)
    is_active: bool | None = None
    available_variables: list[str] | None = None


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
