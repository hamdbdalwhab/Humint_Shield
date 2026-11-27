"""Department model - an organization-scoped group of human assets."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UUIDType, generate_uuid


def _utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class Department(Base):
    """A real, referenceable department inside one organization.

    Human assets used to carry only a free-text ``department`` string.  Those
    strings kept drifting ("IT", "I.T.", "Information Technology"), which made
    department-level reporting unreliable.  This table is the canonical list:
    ``human_assets.department_id`` points at it, while the legacy text column
    is still populated so every existing query and CSV import keeps working.

    The model is additive: an organization can keep operating with free-text
    departments and the service layer derives this table from those values.
    """

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_department_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    manager_name: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship()  # noqa: F821
    employees: Mapped[list["HumanAsset"]] = relationship(  # noqa: F821
        back_populates="department_ref"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Department {self.name!r}>"
