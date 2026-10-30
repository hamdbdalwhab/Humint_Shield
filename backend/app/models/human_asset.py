"""HumanAsset model - the employees being trained."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
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
    #: Corporate sign-in name, when different from the e-mail local part.
    username: Mapped[str | None] = mapped_column(String(150), index=True)
    #: HR/payroll employee number printed on badges and pay slips.
    employee_id_external: Mapped[str | None] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(EncryptedString(64))
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
