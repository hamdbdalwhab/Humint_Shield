"""Pydantic v2 schemas for AI-assisted template generation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


__all__ = ["AIGeneratedTemplate", "AIGenerateTemplateRequest"]
