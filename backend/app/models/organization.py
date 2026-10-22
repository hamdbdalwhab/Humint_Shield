"""Organization model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, JSONBType, UUIDType, generate_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    """A tenant. All data is scoped to exactly one organization."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    allowed_test_hours: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    allow_personal_devices: Mapped[bool] = mapped_column(Boolean, default=False)
    adaptive_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    max_tests_per_day: Mapped[int] = mapped_column(Integer, default=10)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    employees: Mapped[list["HumanAsset"]] = relationship(  # noqa: F821
        back_populates="organization", cascade="all, delete-orphan", lazy="selectin"
    )
    email_templates: Mapped[list["EmailTemplate"]] = relationship(  # noqa: F821
        back_populates="organization", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["EmailCampaign"]] = relationship(  # noqa: F821
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Organization {self.name!r} domain={self.domain!r}>"
