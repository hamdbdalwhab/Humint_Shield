"""EmailCampaign, EmailTracking and TrainingInteraction models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, INETType, JSONBType, UUIDType, generate_uuid

CAMPAIGN_STATUSES = ("draft", "active", "completed", "aborted")
CHANNELS = ("email", "sms", "whatsapp", "qr", "vishing", "pretexting", "usb")
SIMULATION_CHANNELS = ("qr", "vishing", "pretexting", "usb")
DEFAULT_CHANNEL = "email"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmailCampaign(Base):
    """A single authorized simulation run against a set of employees."""

    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','completed','aborted')",
            name="ck_campaign_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("templates.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(20), default=DEFAULT_CHANNEL, server_default=DEFAULT_CHANNEL, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    #: Channel-specific scenario configuration (QR pretext, credential provider,
    #: vishing/pretexting copy).  Keeping it in one JSON column lets all channels
    #: share the same campaign and tracking tables.
    channel_config: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    target_employee_ids: Mapped[list] = mapped_column(JSONBType, default=list)
    total_targets: Mapped[int] = mapped_column(Integer, default=0)
    auto_retest_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="campaigns")  # noqa: F821
    template: Mapped["EmailTemplate | None"] = relationship(back_populates="campaigns")  # noqa: F821
    tracking: Mapped[list["EmailTracking"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<EmailCampaign {self.name!r} status={self.status!r}>"


class EmailTracking(Base):
    """Per-recipient delivery and engagement record.

    ``tracking_uuid`` is an unguessable secret embedded in the tracking pixel,
    the click-wrapped links, and the training page URL.
    """

    __tablename__ = "tracking_events"
    __table_args__ = (
        UniqueConstraint("tracking_uuid", name="uq_tracking_uuid"),
        UniqueConstraint("campaign_id", "employee_id", name="uq_tracking_campaign_employee"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("human_assets.id", ondelete="CASCADE"), index=True, nullable=True
    )
    tracking_uuid: Mapped[uuid.UUID] = mapped_column(
        UUIDType, unique=True, index=True, nullable=False, default=generate_uuid
    )
    short_code: Mapped[str | None] = mapped_column(
        String(16), unique=True, index=True, nullable=True
    )
    otp_submitted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    otp_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("templates.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(
        String(20), default=DEFAULT_CHANNEL, server_default=DEFAULT_CHANNEL, index=True, nullable=False
    )
    event_type: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Provider-neutral delivery receipt state (for example ``submitted``,
    #: ``delivered``, ``read``, ``failed``).  ``None`` for legacy email rows.
    delivery_status: Mapped[str | None] = mapped_column(String(20))
    #: Last provider error, when a delivery failed or was rejected.
    delivery_error: Mapped[str | None] = mapped_column(String(500))
    #: When a WhatsApp read receipt was received.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the provider last reported a failed/rejected delivery.
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Generic provider fields. ``email`` currently uses Brevo; SMS/WhatsApp will
    #: use Vonage without a schema change.
    provider: Mapped[str | None] = mapped_column(String(30), default="brevo")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)
    #: When the interactive training page (or the simulated form) was first rendered.
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When the simulated credential form (or another channel's equivalent) was
    #: first submitted.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Whatever identifier the recipient typed (usually their work email).
    submitted_identifier: Mapped[str | None] = mapped_column(String(255))
    #: Identity values entered on the QR landing form.  Unlike the legacy
    #: ``submitted_identifier`` these are kept separately because the portal
    #: now asks for both a username/employee number and a corporate e-mail.
    submitted_username: Mapped[str | None] = mapped_column(String(150))
    submitted_email: Mapped[str | None] = mapped_column(String(255))
    #: True when a password was typed.  The value itself is never stored for
    #: QR/quishing rows.
    password_submitted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    #: How the entered identity was matched to an employee: ``matched_email``,
    #: ``matched_username``, ``manual`` or ``unknown``.
    identity_resolution: Mapped[str | None] = mapped_column(String(30))
    #: Employee resolved from the values entered on the QR form.  This is kept
    #: separately from ``employee_id`` (the recipient whose poster was scanned)
    #: because someone can scan another person's poster.
    identity_resolved_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, index=True
    )
    #: Whether the once-only -25 quishing penalty has been applied.
    qr_penalty_applied: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    #: Non-secret form fields exactly as entered (kept for quick display/CSV).
    submitted_fields: Mapped[dict | None] = mapped_column(JSONBType)
    #: Length of the password that was typed.
    password_length: Mapped[int | None] = mapped_column(Integer)
    #: AES-256-GCM ciphertext of the password exactly as typed.  Stored only so
    #: an administrator can prove what was entered; never logged in clear text.
    submitted_password_encrypted: Mapped[str | None] = mapped_column(Text)
    #: AES-256-GCM ciphertext of the complete submission payload (every field,
    #: verbatim) as a JSON document.
    submitted_payload_encrypted: Mapped[str | None] = mapped_column(Text)
    #: Non-secret browser context of the submission (client clock, time to
    #: submit, language, timezone, viewport).  Used as behavioural evidence.
    client_context: Mapped[dict | None] = mapped_column(JSONBType)
    #: When the recipient flagged the simulation as suspicious (a good outcome).
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Quiz result: correct answers out of ``quiz_total``.
    quiz_score: Mapped[int | None] = mapped_column(Integer)
    quiz_total: Mapped[int | None] = mapped_column(Integer, default=5)
    #: Set when an administrator records an out-of-band "report safe" for an
    #: employee who recognised and reported the message without clicking.
    is_reported_safe: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_ip_address: Mapped[str | None] = mapped_column(INETType)
    last_user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    campaign: Mapped["EmailCampaign"] = relationship(back_populates="tracking")
    employee: Mapped["HumanAsset"] = relationship(back_populates="tracking_events")  # noqa: F821
    interactions: Mapped[list["TrainingInteraction"]] = relationship(
        back_populates="tracking",
        cascade="all, delete-orphan",
        order_by="TrainingInteraction.occurred_at",
    )

    # ------------------------------------------------------------------ #
    # Backwards-compatible attribute names
    # ------------------------------------------------------------------ #
    # The unified schema uses generic channel-neutral names. These properties
    # keep older call sites (and the pre-0005 audit scripts) working without
    # duplicating data in the database.
    @property
    def email_template_id(self) -> uuid.UUID | None:
        """Deprecated alias for :attr:`template_id`."""
        return self.template_id

    @email_template_id.setter
    def email_template_id(self, value: uuid.UUID | None) -> None:
        self.template_id = value

    @property
    def brevo_message_id(self) -> str | None:
        """Deprecated alias for :attr:`provider_message_id`."""
        return self.provider_message_id

    @brevo_message_id.setter
    def brevo_message_id(self, value: str | None) -> None:
        self.provider_message_id = value

    @property
    def form_viewed_at(self) -> datetime | None:
        """Deprecated alias for :attr:`viewed_at`."""
        return self.viewed_at

    @form_viewed_at.setter
    def form_viewed_at(self, value: datetime | None) -> None:
        self.viewed_at = value

    @property
    def form_submitted_at(self) -> datetime | None:
        """Deprecated alias for :attr:`submitted_at`."""
        return self.submitted_at

    @form_submitted_at.setter
    def form_submitted_at(self, value: datetime | None) -> None:
        self.submitted_at = value

    @property
    def completed_training_at(self) -> datetime | None:
        """Deprecated alias for :attr:`completed_at`."""
        return self.completed_at

    @completed_training_at.setter
    def completed_training_at(self, value: datetime | None) -> None:
        self.completed_at = value

    @property
    def status(self) -> str:
        """Derive a human readable status from the timestamps."""
        if self.is_reported_safe:
            return "reported_safe"
        if self.completed_at is not None:
            return "completed"
        if self.submitted_at is not None:
            return "submitted"
        if self.clicked_at is not None:
            return "clicked"
        if self.opened_at is not None:
            return "opened"
        if self.sent_at is not None:
            return "sent"
        return "pending"

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<EmailTracking {self.tracking_uuid} status={self.status!r}>"


class TrainingInteraction(Base):
    """Append-only log of everything a recipient did with a simulation.

    One row is written for every open, click, form render, submission,
    phishing report and completion.  ``occurred_at`` keeps microsecond
    precision, so the dashboard can show the exact second of every state
    transition, and repeated actions (a second open, a third submission) are
    preserved instead of being collapsed into a counter.

    Secret values (the password and the raw submission payload) are encrypted
    with AES-256-GCM before they reach this table.
    """

    __tablename__ = "training_interactions"
    __table_args__ = (
        Index("ix_training_interactions_campaign_time", "campaign_id", "occurred_at"),
        Index("ix_training_interactions_employee_time", "employee_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    tracking_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tracking_events.id", ondelete="CASCADE"), index=True, nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("human_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: ``email_open``, ``link_click``, ``form_viewed``, ``form_submitted``,
    #: ``phishing_reported`` or ``training_completed``.
    event_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INETType)
    user_agent: Mapped[str | None] = mapped_column(Text)
    #: Non-secret structured context (counters, form field names, durations).
    details: Mapped[dict | None] = mapped_column(JSONBType)
    #: AES-256-GCM ciphertext of the event's secret payload, when it has one.
    payload_encrypted: Mapped[str | None] = mapped_column(Text)

    tracking: Mapped["EmailTracking"] = relationship(back_populates="interactions")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TrainingInteraction {self.event_type!r} at={self.occurred_at!r}>"


class QRScan(Base):
    """One credential-form submission from a QR/quishing landing page.

    This is the canonical "Live scans" record for QR campaigns.  Unlike the
    legacy :class:`EmailTracking` row it can exist without a pre-created
    recipient row, which lets a campaign-level QR link still record an
    unmatched ("Unknown scan") attempt for an administrator to assign later.

    No secret is ever stored here.  ``password_submitted`` is a boolean only.
    """

    __tablename__ = "qr_scans"
    __table_args__ = (
        Index("ix_qr_scans_campaign_time", "campaign_id", "occurred_at"),
        Index("ix_qr_scans_employee_time", "employee_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: The recipient tracking row whose poster/QR was used, when one exists.
    tracking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("tracking_events.id", ondelete="SET NULL"), index=True
    )
    #: The employee resolved from the entered e-mail/username, or an employee
    #: assigned manually by an administrator.
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("human_assets.id", ondelete="SET NULL"), index=True
    )
    username: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    password_submitted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    #: ``matched_email``, ``matched_username``, ``manual`` or ``unknown``.
    identity_resolution: Mapped[str] = mapped_column(
        String(30), default="unknown", server_default="unknown", nullable=False
    )
    #: Browser evidence such as screen size, timezone and submission delay.
    fingerprint_data: Mapped[dict | None] = mapped_column(JSONBType)
    #: The -25 Elo delta, recorded once per employee/campaign.
    elo_delta: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    penalty_applied: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(INETType)
    user_agent: Mapped[str | None] = mapped_column(Text)
    device_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    isp: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    real_time_events: Mapped[list | None] = mapped_column(JSONBType, default=list)
    event_type: Mapped[str] = mapped_column(
        String(40), default="qr_scanned", server_default="qr_scanned", nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<QRScan {self.id} campaign={self.campaign_id} resolution={self.identity_resolution!r}>"
