"""ShortLink model: SMS-safe links that hide the tracking URL."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UUIDType, generate_uuid


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class ShortLink(Base):
    """A short code mapped to a simulation landing page.

    SMS bodies must never expose the full tracking URL (long, and it reveals the
    infrastructure).  Each recipient gets a 6-character code stored here; the
    public ``/s/{code}`` endpoint records the click and redirects.
    """

    __tablename__ = "short_links"
    # Keep the physical schema in sync with migration 0015: a named unique
    # constraint plus a plain lookup index.  Declaring ``unique=True`` and
    # ``index=True`` together would instead emit one unique index and make
    # ``alembic check`` report perpetual drift.
    __table_args__ = (
        UniqueConstraint("code", name="uq_short_links_code"),
        Index("ix_short_links_code", "code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    tracking_uuid: Mapped[uuid.UUID] = mapped_column(UUIDType, index=True, nullable=False)
    target_path: Mapped[str] = mapped_column(String(500), nullable=False)
    #: Message-safe URL (custom short domain, or an external shortener result).
    display_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    last_clicked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ShortLink {self.code!r} -> {self.target_path!r}>"
