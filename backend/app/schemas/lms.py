"""Pydantic v2 schemas: LMS (training library, assignments, report inbox)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrainingModulePublic(BaseModel):
    """Training module representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    title: str
    summary: str | None = None
    content_html: str
    category: str | None = None
    duration_minutes: int
    difficulty_level: int
    is_active: bool
    created_at: datetime


class TrainingModuleCreate(BaseModel):
    """Payload for creating a training module."""

    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    content_html: str = ""
    category: str | None = None
    duration_minutes: int = Field(default=10, ge=1, le=600)
    difficulty_level: int = Field(default=3, ge=1, le=10)


class AssignmentPublic(BaseModel):
    """Assignment representation with embedded module + employee info."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    module_id: uuid.UUID
    employee_id: uuid.UUID | None
    status: str
    due_date: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    module_title: str | None = None
    employee_name: str | None = None
    employee_email: str | None = None


class AssignmentCreate(BaseModel):
    """Payload for creating an assignment."""

    module_id: uuid.UUID
    employee_id: uuid.UUID | None = None
    due_date: datetime | None = None
    notes: str | None = None


class PhishingReportPublic(BaseModel):
    """Report-inbox entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID | None = None
    reported_email_subject: str | None = None
    reported_sender: str | None = None
    description: str | None = None
    status: str
    is_training_simulation: bool
    triage_notes: str | None = None
    created_at: datetime


class PhishingReportCreate(BaseModel):
    """Payload for filing a report (also used by the training page)."""

    employee_id: uuid.UUID | None = None
    reported_email_subject: str | None = None
    reported_sender: str | None = None
    description: str | None = None
    is_training_simulation: bool = False


class PhishingReportUpdate(BaseModel):
    """Payload for triaging a report."""

    status: str | None = Field(default=None, pattern="^(new|triage|resolved|false_positive)$")
    triage_notes: str | None = None


class DashboardSummary(BaseModel):
    """Aggregate numbers for the dashboard page."""

    total_employees: int
    active_employees: int
    total_campaigns: int
    active_campaigns: int
    total_templates: int
    total_emails_sent: int
    total_opened: int
    total_clicked: int
    total_submitted: int = 0
    total_completed: int
    open_rate: float
    click_rate: float
    submission_rate: float = 0.0
    reports_pending: int
    critical_risk_employees: int
    recent_campaigns: list[dict] = Field(default_factory=list)
    #: Newest ledger entries across every campaign (live activity feed).
    recent_events: list[dict] = Field(default_factory=list)
    #: Seven-day engagement series: opens, clicks, submissions and completions.
    engagement_trend: list[dict] = Field(default_factory=list)
