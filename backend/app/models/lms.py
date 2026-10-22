"""Existing LMS models: training modules, assignments and the report inbox.

These back the pre-existing Learning Management System pages (Training
Library, Assignments, My Training, Report Inbox).  The campaign subsystem only
*adds* to these and never mutates them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, JSONBType, UUIDType, generate_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrainingModule(Base):
    """A self-paced learning module shown in the Training Library."""

    __tablename__ = "training_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(100))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=10)
    difficulty_level: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    assignments: Mapped[list["TrainingAssignment"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )


class TrainingAssignment(Base):
    """Assigns a training module to an employee (Assignments / My Training)."""

    __tablename__ = "training_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("training_modules.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("human_assets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    module: Mapped["TrainingModule"] = relationship(back_populates="assignments")
    employee: Mapped["HumanAsset | None"] = relationship()  # noqa: F821


class PhishingReport(Base):
    """A user-submitted suspicious-email report (Report Inbox)."""

    __tablename__ = "phishing_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("human_assets.id", ondelete="SET NULL"), index=True
    )
    reported_email_subject: Mapped[str | None] = mapped_column(String(500))
    reported_sender: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="new")
    is_training_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    triage_notes: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONBType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
