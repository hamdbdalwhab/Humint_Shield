"""Pydantic v2 schemas: campaigns and tracking."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.employee import EmployeePublic


class CampaignBase(BaseModel):
    """Shared campaign fields."""

    name: str = Field(min_length=1, max_length=255)
    template_id: uuid.UUID
    channel: str = Field(
        default="email", pattern="^(email|sms|whatsapp|qr|vishing|pretexting|usb)$"
    )
    difficulty_level: int = Field(default=5, ge=1, le=10)
    auto_retest_failed: bool = False
    channel_config: dict[str, Any] | None = None


class CampaignCreate(CampaignBase):
    """Payload for creating a campaign (starts in ``draft``)."""

    target_employee_ids: list[uuid.UUID] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    """Partial update payload; only allowed while ``status == 'draft'``."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    template_id: uuid.UUID | None = None
    channel: str | None = Field(
        default=None, pattern="^(email|sms|whatsapp|qr|vishing|pretexting|usb)$"
    )
    difficulty_level: int | None = Field(default=None, ge=1, le=10)
    auto_retest_failed: bool | None = None
    channel_config: dict[str, Any] | None = None
    target_employee_ids: list[uuid.UUID] | None = None


class CampaignPublic(BaseModel):
    """Campaign representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    template_id: uuid.UUID | None
    name: str
    channel: str = "email"
    channel_config: dict[str, Any] | None = None
    status: str
    auto_retest_failed: bool = False
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
    tracking_uuid: uuid.UUID | None = None
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
    submitted_username: str | None = None
    submitted_email: str | None = None
    password_submitted: bool = False
    identity_resolution: str | None = None
    identity_resolved_employee_id: uuid.UUID | None = None
    identity_resolved_name: str | None = None
    identity_resolved_email: str | None = None
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
    submitted_username: str | None = None
    submitted_email: str | None = None
    password_submitted: bool = False
    identity_resolution: str | None = None
    identity_resolved_employee_id: uuid.UUID | None = None
    identity_resolved_name: str | None = None
    identity_resolved_email: str | None = None
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


class QRScanPublic(BaseModel):
    """One entry of the QR campaign's "Live scans" table.

    ``employee_id`` is the identity resolved from the entered username/e-mail
    (or assigned manually).  It is deliberately separate from
    ``source_employee_id``, which is the owner of the QR poster that was used.
    """

    id: uuid.UUID
    campaign_id: uuid.UUID
    tracking_id: uuid.UUID | None = None
    tracking_uuid: uuid.UUID | None = None
    source_employee_id: uuid.UUID | None = None
    source_employee_name: str | None = None
    source_employee_email: str | None = None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None
    employee_email: str | None = None
    username: str | None = None
    email: str | None = None
    password_submitted: bool = False
    identity_resolution: str = "unknown"
    event_type: str = "qr_scanned"
    occurred_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    #: Canvas/WebGL/screen/CPU/timezone evidence collected on the landing page.
    fingerprint: dict[str, Any] = Field(default_factory=dict)
    fingerprint_hash: str | None = None
    username_entered: str | None = None
    email_entered: str | None = None
    device_info: dict[str, Any] = Field(default_factory=dict)
    device_model: str | None = None
    device_real_name: str | None = None
    local_ip: str | None = None
    gpu_renderer: str | None = None
    hardware_fingerprint: str | None = None
    country: str | None = None
    city: str | None = None
    isp: str | None = None
    location_display: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    real_time_events: list[dict[str, Any]] = Field(default_factory=list)
    time_on_page_seconds: int = 0
    elo_delta: int = 0
    penalty_applied: bool = False


class QRScanAssignRequest(BaseModel):
    """Administrator action for an unmatched QR scan."""

    employee_id: uuid.UUID


class QRScanAssignResponse(BaseModel):
    """Result of assigning an unmatched scan to an employee."""

    success: bool
    message: str = ""
    scan: QRScanPublic | None = None
    elo_score: int | None = None
    elo_delta: int = 0


class CampaignResults(BaseModel):
    """Response from ``GET /email-campaigns/{id}/results``."""

    campaign: CampaignPublic
    stats: CampaignStats
    employees: list[CampaignEmployeeResult]
    #: QR campaigns only: every submitted scan, including unknown identities.
    scans: list[QRScanPublic] = Field(default_factory=list)


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


class QRSubmissionRequest(BaseModel):
    """Body for ``POST /track/qr/submit``.

    The browser must never transmit the typed password value.  The field is
    accepted for compatibility with clients that still include it, but it is
    deliberately ignored by the endpoint and never written to the database.
    Only the boolean ``password_submitted`` (and non-secret browser evidence)
    is retained.
    """

    campaign_id: uuid.UUID
    tracking_uuid: uuid.UUID | None = None
    username: str = Field(min_length=1, max_length=150)
    email: EmailStr
    #: Accepted for contract compatibility only.  Never logged or persisted.
    password: str | None = Field(default=None, max_length=1024)
    password_submitted: bool = True
    fingerprint_data: dict[str, Any] = Field(default_factory=dict)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)


class QRSubmissionResponse(BaseModel):
    """Result of a QR/quishing credential submission."""

    success: bool
    status: str = "success"
    redirect: str | None = None
    redirect_url: str | None = None
    first_time: bool = False
    unknown: bool = False
    message: str = ""
    identity_resolution: str | None = None
    resolved_employee_id: uuid.UUID | None = None
    resolved_employee_name: str | None = None
    tracking_uuid: uuid.UUID | None = None
    elo_delta: int = 0
    elo_score: int | None = None


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
    #: When ``False`` the backend records only non-secret metadata and never
    #: persists the typed password.  The React credential pages always send
    #: ``False``; legacy API clients default to the historical behaviour.
    capture_secret: bool = True


class OTPVerifyRequest(BaseModel):
    """Payload for submitting a 6-digit MFA / OTP verification code."""

    otp_code: str = Field(min_length=1, max_length=20)


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


class SimulationChoiceRequest(BaseModel):
    """Choice made on a vishing or pretexting simulation page."""

    choice: str = Field(
        pattern="^(credential_disclosed|financial_fraud|reported_phish)$"
    )


class SimulationChoiceResponse(BaseModel):
    """Result of a vishing/pretexting choice, including the updated Elo."""

    success: bool
    choice: str
    message: str = ""
    already_recorded: bool = False
    elo_score: int | None = None
    threat_level: str | None = None
    redirect_url: str | None = None


class QRPosterRequest(BaseModel):
    """Optional copy and branding overrides for a quishing poster pack."""

    headline: str | None = Field(default=None, max_length=180)
    body: str | None = Field(default=None, max_length=1200)
    footer: str | None = Field(default=None, max_length=240)
    pretext_key: str | None = Field(default=None, max_length=60)
    #: One of ``coffee``, ``bonus``, ``nomination``, ``hr`` or ``wifi``.
    lure_type: str | None = Field(default=None, max_length=40)
    company_name: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    #: ``2026-05`` or a free-text month label for the nomination lure.
    month_label: str | None = Field(default=None, max_length=80)
    primary_color: str | None = Field(default=None, max_length=20)
    accent_color: str | None = Field(default=None, max_length=20)
    #: ``data:image/png;base64,...`` (max ~1.5 MB decoded).
    logo_data_url: str | None = Field(default=None, max_length=2_100_000)


class USBPDFRequest(BaseModel):
    """Optional document metadata for a safe USB-drop PDF pack.

    The awareness warning itself is fixed in the renderer and cannot be
    overridden.  Only the downloaded document name and the visible month label
    are operator-configurable.
    """

    document_name: str | None = Field(default=None, max_length=120)
    month_label: str | None = Field(default=None, max_length=80)
