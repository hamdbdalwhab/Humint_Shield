"""HumanAsset model - the employees being trained."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, JSONBType, UUIDType, generate_uuid
from app.models.types import EncryptedString


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HumanAsset(Base):
    """An employee enrolled in the awareness program.

    ``phone`` is encrypted at rest with AES-256-GCM via :class:`EncryptedString`.
    """

    __tablename__ = "human_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    #: AES-256-GCM sealed copy of :attr:`email` (``BYTEA``).  The plaintext
    #: column is retained for the unique index and case-insensitive search.
    email_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    #: Corporate sign-in name, when different from the e-mail local part.
    username: Mapped[str | None] = mapped_column(String(150), index=True)
    #: HR/payroll employee number printed on badges and pay slips.
    employee_id_external: Mapped[str | None] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(EncryptedString(64))
    #: AES-256-GCM sealed copy of :attr:`phone` in the byte format used by
    #: :mod:`app.services.encryption_service`.
    phone_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    department: Mapped[str | None] = mapped_column(String(100), index=True)
    job_title: Mapped[str | None] = mapped_column(String(100))
    access_level: Mapped[int] = mapped_column(Integer, default=1)
    immunity_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("50.00"))
    #: Elo-style adaptive-difficulty rating.  Starts at 1000 for every employee;
    #: the first click is -32 and the first report is +32.
    elo_score: Mapped[int] = mapped_column(
        Integer, default=1000, server_default="1000", nullable=False
    )
    behavioral_category: Mapped[str | None] = mapped_column(String(20), default="hesitant")
    total_tests_received: Mapped[int] = mapped_column(Integer, default=0)
    total_clicks: Mapped[int] = mapped_column(Integer, default=0)
    total_reports: Mapped[int] = mapped_column(Integer, default=0)
    total_credential_submissions: Mapped[int] = mapped_column(Integer, default=0)
    total_ignores: Mapped[int] = mapped_column(Integer, default=0)
    last_test_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_test_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_on_leave: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_mandatory_training: Mapped[bool] = mapped_column(Boolean, default=False)
    under_enhanced_monitoring: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Repeated-failure blacklist (module 4).  Blacklisted employees are only
    #: eligible for campaigns explicitly marked as mandatory training.
    is_blacklisted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    blacklist_reason: Mapped[str | None] = mapped_column(String(100))
    blacklisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_profile: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    risk_profile: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    behavioral_baseline: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="employees")  # noqa: F821
    tracking_events: Mapped[list["EmailTracking"]] = relationship(  # noqa: F821
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        """Return the employee's display name."""
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<HumanAsset {self.email!r}>"


def _seal_sensitive_columns(target: HumanAsset) -> None:
    """Mirror the plaintext columns into their encrypted ``BYTEA`` copies.

    Running on the ORM flush guarantees that every write path (single create,
    CSV import, update, seeding) keeps the encrypted columns in sync without
    each endpoint having to remember it.
    """
    from app.services.encryption_service import encrypt_text

    if target.email:
        target.email_encrypted = encrypt_text(str(target.email))
    target.phone_encrypted = (
        encrypt_text(str(target.phone)) if target.phone else None
    )


@event.listens_for(HumanAsset, "before_insert")
def _seal_on_insert(mapper, connection, target: HumanAsset) -> None:  # noqa: ANN001
    """Encrypt PII before a new row is written."""
    _seal_sensitive_columns(target)


@event.listens_for(HumanAsset, "before_update")
def _seal_on_update(mapper, connection, target: HumanAsset) -> None:  # noqa: ANN001
    """Re-seal PII after an update (new nonce on every write)."""
    _seal_sensitive_columns(target)
