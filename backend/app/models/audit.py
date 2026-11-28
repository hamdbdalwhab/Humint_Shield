"""Audit-trail and JWT revocation tables (enterprise compliance)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONBType, UUIDType, generate_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    """An immutable record of a privileged change.

    Every row answers *who* changed *what*, *when*, from *where* and keeps the
    before/after snapshots so an auditor can reconstruct the mutation without
    replaying application logs.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_target", "target_table", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    #: ``CREATE`` / ``UPDATE`` / ``DELETE``.
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[dict | None] = mapped_column(JSONBType)
    new_value: Mapped[dict | None] = mapped_column(JSONBType)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AuditLog {self.action} {self.target_table}:{self.target_id}>"


class TokenRevocation(Base):
    """A single revoked JWT, identified by its ``jti`` claim.

    ``users.token_version`` invalidates every token of an account at once; this
    table lets a single session (the presented token) be revoked precisely and
    leaves an auditable reason behind.
    """

    __tablename__ = "token_revocations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_jti: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    #: ``LOGOUT`` / ``PASSWORD_CHANGE`` / ``ADMIN_ACTION``.
    reason: Mapped[str] = mapped_column(String(32), default="LOGOUT", nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<TokenRevocation {self.token_jti} {self.reason}>"
