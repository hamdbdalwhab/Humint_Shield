"""Monthly Elo archives and certificate data (module 2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UUIDType, generate_uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MonthlyArchive(Base):
    """Immutable snapshot of one employee's score and monthly behaviour.

    A row is written by the last-day-of-month Celery task immediately before the
    live Elo score is reset to :data:`~app.services.elo_engine.INITIAL_ELO`.
    The unique constraint makes the task idempotent: re-running it for the same
    month updates the snapshot instead of creating a duplicate.
    """

    __tablename__ = "monthly_archives"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "month_year", name="uq_monthly_archive_employee_month"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=generate_uuid)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("human_assets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Calendar month in ``YYYY-MM`` form.
    month_year: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    final_elo_score: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    total_reports: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_submissions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    employee: Mapped["HumanAsset"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MonthlyArchive employee={self.employee_id} month={self.month_year!r} "
            f"elo={self.final_elo_score}>"
        )
