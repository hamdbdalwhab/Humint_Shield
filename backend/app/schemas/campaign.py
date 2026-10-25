"""Pydantic v2 schemas: campaigns and tracking."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.employee import EmployeePublic


class CampaignBase(BaseModel):
    """Shared campaign fields."""

    name: str = Field(min_length=1, max_length=255)
    template_id: uuid.UUID
    channel: str = Field(default="email", pattern="^(email|sms|whatsapp)$")
    difficulty_level: int = Field(default=5, ge=1, le=10)


class CampaignCreate(CampaignBase):
    """Payload for creating a campaign (starts in ``draft``)."""

    target_employee_ids: list[uuid.UUID] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    """Partial update payload; only allowed while ``status == 'draft'``."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_id: uuid.UUID | None = None
    channel: str | None = Field(default=None, pattern="^(email|sms|whatsapp)$")
    difficulty_level: int | None = Field(default=None, ge=1, le=10)
    target_employee_ids: list[uuid.UUID] | None = None


class CampaignPublic(BaseModel):
    """Campaign representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    template_id: uuid.UUID | None
    name: str
    channel: str = "email"
    status: str
    target_employee_ids: list[str]
    total_targets: int
    sent_count: int
    failed_count: int
    opened_count: int
    clicked_count: int
    completed_count: int
    launched_at: datetime | None
    completed_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @field_validator("target_employee_ids", mode="before")
    @classmethod
    def _coerce_targets(cls, value: object) -> object:
        """Ensure the JSONB target list is always a list of strings."""
        if value is None:
            return []
        return [str(v) for v in value]


class LaunchFailure(BaseModel):
    """A single failed send."""

    employee_id: uuid.UUID
    email: str
    error: str


class LaunchResult(BaseModel):
    """Response from ``POST /email-campaigns/{id}/launch``."""

    campaign_id: uuid.UUID
    total: int
    sent: int
    failed: int
    failures: list[LaunchFailure] = Field(default_factory=list)


class CampaignStats(BaseModel):
    """Aggregate engagement statistics."""

    total: int
    sent: int
    failed: int
    opened: int
    clicked: int
    submitted: int = 0
    completed: int
    open_rate: float
    click_rate: float
    submission_rate: float = 0.0
    completion_rate: float


class CampaignEmployeeResult(BaseModel):
    """Per-employee engagement row."""

    employee_id: uuid.UUID
    name: str
    email: str
    phone: str | None = None
    channel: str = "email"
    department: str | None = None
    job_title: str | None = None
    status: str
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    delivery_status: str | None = None
    delivery_error: str | None = None
    read_at: datetime | None = None
    failed_at: datetime | None = None
    provider_message_id: str | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    form_viewed_at: datetime | None = None
    reported_at: datetime | None = None
    quiz_score: int | None = None
    quiz_total: int | None = None
    is_reported_safe: bool = False
    open_count: int = 0
    click_count: int = 0
    submission_count: int = 0
    submitted_identifier: str | None = None
    submitted_fields: dict[str, str] | None = None
    #: Every value the recipient typed, decrypted (includes the password).
    submitted_values: dict[str, str] | None = None
    password_length: int | None = None
    immunity_score: float | None = None
    behavioral_category: str | None = None
    elo_score: int | None = None
    threat_level: str | None = None
    template_name: str | None = None
    template_difficulty: int | None = None
    error: str | None = None


class InteractionPublic(BaseModel):
    """One entry of the append-only interaction ledger."""

    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] | None = None
    #: Decrypted secret payload — present for ``form_submitted`` events.
    values: dict[str, str] | None = None
    #: Filled in by the campaign-wide activity feed only.
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    employee_email: str | None = None
    department: str | None = None
    #: Filled in by the merged per-employee timeline only.
    campaign_id: uuid.UUID | None = None
    campaign_name: str | None = None


class SubmissionPublic(BaseModel):
    """A single, complete credential-form submission."""

    occurred_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    password_length: int | None = None
    client: dict[str, Any] | None = None
    values: dict[str, str] = Field(default_factory=dict)
    campaign_id: uuid.UUID | None = None
    campaign_name: str | None = None


class EmployeeCampaignRecord(BaseModel):
    """Everything one employee did inside one campaign."""

    campaign_id: uuid.UUID
    campaign_name: str
    campaign_status: str
    template_name: str | None = None
    channel: str = "email"
    tracking_uuid: uuid.UUID
    status: str
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    delivery_status: str | None = None
    delivery_error: str | None = None
    read_at: datetime | None = None
    failed_at: datetime | None = None
    provider_message_id: str | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    form_viewed_at: datetime | None = None
    submitted_at: datetime | None = None
    reported_at: datetime | None = None
    completed_at: datetime | None = None
    quiz_score: int | None = None
    quiz_total: int | None = None
    is_reported_safe: bool = False
    open_count: int = 0
    click_count: int = 0
    submission_count: int = 0
    submitted_identifier: str | None = None
    submitted_fields: dict[str, str] | None = None
    submitted_values: dict[str, str] | None = None
    client_context: dict[str, Any] | None = None
    events: list[InteractionPublic] = Field(default_factory=list)
    submissions: list[SubmissionPublic] = Field(default_factory=list)


class EmployeeSummary(BaseModel):
    """Aggregate engagement for one employee across every campaign."""

    campaigns: int = 0
    emails_sent: int = 0
    opened: int = 0
    clicked: int = 0
    submitted: int = 0
    reported: int = 0
    completed: int = 0
    total_interactions: int = 0
    first_interaction_at: datetime | None = None
    last_interaction_at: datetime | None = None


class EmployeeDossier(BaseModel):
    """Complete, per-second dossier for one employee."""

    employee: EmployeePublic
    summary: EmployeeSummary
    campaigns: list[EmployeeCampaignRecord] = Field(default_factory=list)
    events: list[InteractionPublic] = Field(default_factory=list)
    submissions: list[SubmissionPublic] = Field(default_factory=list)


class CampaignRecipientDetail(BaseModel):
    """One recipient's full record inside one campaign."""

    campaign: CampaignPublic
    employee: EmployeePublic
    record: EmployeeCampaignRecord


class CampaignActivity(BaseModel):
    """The campaign-wide interaction ledger."""

    campaign: CampaignPublic
    stats: CampaignStats
    events: list[InteractionPublic] = Field(default_factory=list)


class CampaignResults(BaseModel):
    """Response from ``GET /email-campaigns/{id}/results``."""

    campaign: CampaignPublic
    stats: CampaignStats
    employees: list[CampaignEmployeeResult]


class TrackingCompleteResponse(BaseModel):
    """Response from ``POST /track/complete/{tracking_uuid}``."""

    success: bool
    already_completed: bool = False
    message: str = ""
    quiz_score: int | None = None
    quiz_total: int | None = None
    immunity_score: float | None = None
    behavioral_category: str | None = None


class TrainingCompleteRequest(BaseModel):
    """Quiz result posted by the interactive training page.

    ``score`` is the number of correct answers and ``total`` the number of
    questions.  The response stores the raw pair; percentages are derived by
    the dashboard.
    """

    score: int = Field(ge=0, le=100)
    total: int = Field(default=5, ge=1, le=100)

    @model_validator(mode="after")
    def _score_within_total(self) -> "TrainingCompleteRequest":
        """Reject impossible scores before they reach the database."""
        if self.score > self.total:
            raise ValueError("score cannot exceed total")
        return self


class ReportSafeResponse(BaseModel):
    """Response from the admin ``POST /track/report-safe/{tracking_uuid}``."""

    success: bool
    message: str = ""
    quiz_score: int | None = None
    quiz_total: int | None = None
    immunity_score: float | None = None
    behavioral_category: str | None = None
    already_reported_safe: bool = False


class TrainingSubmission(BaseModel):
    """Body for ``POST /track/submit/{tracking_uuid}``.

    The form transmits every value it contained so the dashboard can prove
    exactly what an employee entered, even if they later claim it was fake.
    ``fields`` carries every named input verbatim, ``password`` the password
    value, and ``client`` a small set of non-secret browser timings used as
    behavioural evidence.
    """

    identifier: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    password_length: int | None = Field(default=None, ge=0, le=1024)
    fields: dict[str, str] = Field(default_factory=dict)
    client: dict[str, Any] | None = None


class TrainingInteractionResponse(BaseModel):
    """Response from the training-page interaction endpoints."""

    success: bool
    first_time: bool = False
    message: str = ""
    immunity_score: float | None = None
    behavioral_category: str | None = None


class TestEmailRequest(BaseModel):
    """Body for ``POST /test/brevo``."""

    to_email: str = Field(min_length=3, max_length=255)
