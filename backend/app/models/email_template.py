"""EmailTemplate model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, JSONBType, UUIDType, generate_uuid

DEFAULT_VARIABLES = [
    "first_name",
    "last_name",
    "email",
    "department",
    "company_name",
    "manager_name",
]

#: Channels supported by the unified campaign schema. ``sms`` templates are
#: delivered by the TextBee gateway; ``qr`` templates carry the printed
#: quishing lure (one generic poster per campaign) and are never emailed.
CHANNELS = ("email", "sms", "whatsapp", "qr")
DEFAULT_CHANNEL = "email"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EmailTemplate(Base):
    """A reusable, personalised phishing-simulation email template."""

    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel: Mapped[str] = mapped_column(
        String(20), default=DEFAULT_CHANNEL, server_default=DEFAULT_CHANNEL, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    #: Visual-editor source document (Unlayer-style JSON).  ``body_html`` is the
    #: compiled, sanitised output that is actually sent.
    design_json: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    #: Optional audience: ``IT``, ``Finance``, ``HR``, ``Executive`` or ``All``.
    #: The SMS landing page picks its skin from this value.
    target_department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    difficulty_level: Mapped[int] = mapped_column(Integer, default=5)
    available_variables: Mapped[list] = mapped_column(
        JSONBType, default=lambda: list(DEFAULT_VARIABLES)
    )
    is_built_in: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="email_templates")  # noqa: F821
    campaigns: Mapped[list["EmailCampaign"]] = relationship(back_populates="template")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<EmailTemplate {self.name!r} builtin={self.is_built_in}>"
