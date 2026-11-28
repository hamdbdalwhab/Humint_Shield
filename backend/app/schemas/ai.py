"""Pydantic v2 schemas for AI-assisted template generation."""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.sanitization import sanitize_plain_text


class AIGenerateTemplateRequest(BaseModel):
    """Inputs for generating one phishing-awareness template.

    The organization's industry is not accepted from the client: it is loaded
    from the authenticated user's organization so a caller cannot make the model
    write for a different tenant.
    """

    target_department: str = Field(min_length=1, max_length=120)
    scenario: str = Field(min_length=3, max_length=1200)
    channel: Literal["email", "sms", "whatsapp"] = "email"

    @field_validator("target_department", "scenario", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        """Trim surrounding whitespace and reject whitespace-only input."""
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("value must not be blank")
            return cleaned
        return value


class AIGeneratedTemplate(BaseModel):
    """Validated, sanitized template returned to the dashboard.

    The frontend autofills these three fields into the existing Create Template
    form; the administrator still reviews and saves the template explicitly.
    """

    subject: str = Field(min_length=1, max_length=300)
    body_html: str = Field(min_length=1, max_length=50_000)
    difficulty_level: int = Field(ge=1, le=10)
    provider: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=120)


class PretextType(str, Enum):
    """The five psychological triggers a training pretext may rely on."""

    authority = "authority"
    urgency = "urgency"
    familiarity = "familiarity"
    scarcity = "scarcity"
    fear = "fear"


#: Arabic label stored alongside the pretext tag (analytics + UI).
PRETEXT_LABELS_AR: dict[str, str] = {
    "authority": "السلطة",
    "urgency": "العجلة",
    "familiarity": "الألفة",
    "scarcity": "الندرة",
    "fear": "الخوف",
}


class PretextGenerateRequest(BaseModel):
    """The exact inputs the pretext engine needs.

    The organization's industry and name default to the authenticated tenant when
    the caller omits them, so a campaign can never be written for another
    organization by supplying a different ``company_name``.
    """

    employee_name: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    industry: str | None = Field(default=None, max_length=120)
    pretext: PretextType
    channel: Literal["email", "sms", "whatsapp"] = "email"
    #: ``ar`` = general formal Arabic, ``ar-SA`` = Saudi corporate Arabic.
    language: Literal["ar", "ar-SA"] = "ar"
    #: Persist the generated template in the ``templates`` table.
    save: bool = True

    @field_validator(
        "employee_name", "job_title", "department", "company_name", "industry", mode="before"
    )
    @classmethod
    def _clean_plain_text(cls, value: object) -> object:
        """Strip markup and reject active content in every free-text input."""
        if value is None:
            return None
        cleaned = sanitize_plain_text(str(value), "pretext input")
        if cleaned is not None:
            cleaned = cleaned.strip()
            if not cleaned and value:
                raise ValueError("value must not be blank")
        return cleaned


class PretextTemplatePayload(BaseModel):
    """The JSON contract the model must return."""

    subject: str = Field(min_length=1, max_length=300)
    body_text: str = Field(min_length=1, max_length=4000)
    pretext_used: PretextType


class PretextTemplateResult(PretextTemplatePayload):
    """A validated pretext template plus its provenance."""

    channel: Literal["email", "sms", "whatsapp"] = "email"
    #: ``ai`` when the model produced it, ``fallback`` for the curated template.
    source: Literal["ai", "fallback"] = "ai"
    provider: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=120)
    template_id: uuid.UUID | None = None


__all__ = [
    "AIGeneratedTemplate",
    "AIGenerateTemplateRequest",
    "PRETEXT_LABELS_AR",
    "PretextGenerateRequest",
    "PretextTemplatePayload",
    "PretextTemplateResult",
    "PretextType",
]
