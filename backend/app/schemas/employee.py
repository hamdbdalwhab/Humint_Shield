"""Pydantic v2 schemas: employees (human assets)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    """A generic page of results."""

    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int


class EmployeeBase(BaseModel):
    """Shared employee fields."""

    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(default="", max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=100)
    access_level: int = Field(default=1, ge=1, le=5)
    is_active: bool = True
    is_on_leave: bool = False


class EmployeeCreate(EmployeeBase):
    """Payload for creating an employee."""


class EmployeeUpdate(BaseModel):
    """Partial update payload for an employee."""

    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=100)
    access_level: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None
    is_on_leave: bool | None = None


class EmployeePublic(BaseModel):
    """Employee representation returned by the API.

    ``immunity_score`` is serialised as a float.  The encrypted ``phone``
    column is transparently decrypted by SQLAlchemy on load.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    phone: str | None = None
    first_name: str
    last_name: str
    department: str | None = None
    job_title: str | None = None
    access_level: int
    immunity_score: float
    behavioral_category: str | None = None
    total_tests_received: int
    total_clicks: int
    total_reports: int
    total_credential_submissions: int
    total_ignores: int
    last_test_date: datetime | None = None
    next_test_date: date | None = None
    is_active: bool
    is_on_leave: bool
    requires_mandatory_training: bool
    under_enhanced_monitoring: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("immunity_score", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: object) -> object:
        """Coerce ``Decimal`` scores to ``float`` for JSON serialisation."""
        if value is None:
            return 0.0
        return float(value)


class TimelineEvent(BaseModel):
    """A single event in an employee's timeline."""

    event_type: str
    timestamp: datetime
    campaign_id: uuid.UUID | None = None
    campaign_name: str | None = None
    details: dict | None = None


class BulkImportResult(BaseModel):
    """Result of a CSV bulk import."""

    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
