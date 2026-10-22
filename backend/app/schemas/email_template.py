"""Pydantic v2 schemas: email templates."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailTemplateBase(BaseModel):
    """Shared template fields."""

    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=500)
    body_html: str = Field(min_length=1)
    difficulty_level: int = Field(default=5, ge=1, le=10)
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    """Payload for creating a template."""

    available_variables: list[str] | None = None


class EmailTemplateUpdate(BaseModel):
    """Partial update payload for a template."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    body_html: str | None = Field(default=None, min_length=1)
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
    missing_variables: list[str] = Field(default_factory=list)
