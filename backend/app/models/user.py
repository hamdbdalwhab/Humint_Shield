"""User model (admin / manager / viewer accounts)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UUIDType, generate_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An operator of the platform."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="admin", nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Monotonic session generation.  Every token carries the value it was
    #: issued with; incrementing it (password change, logout) invalidates all
    #: access and refresh tokens for the account at once.
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    #: Consecutive failed sign-ins.  Reaching ``login_max_attempts`` locks the
    #: account until ``locked_until`` (OWASP account-lockout control).
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Extra permissions granted on top of the role preset.  An account's
    #: effective permissions are ``role preset ∪ permissions`` (see
    #: :mod:`app.permissions`); a ``custom`` role starts with an empty preset so
    #: the account holds exactly what is granted here.
    permissions: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    #: Last successful sign-in, surfaced in the operator administration table.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    organization: Mapped["Organization | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.username!r} role={self.role!r}>"
