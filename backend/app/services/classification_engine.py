"""Behavioral classification engine.

Implements the scoring and categorisation rules that place each employee into
one of four behavioural buckets based on the last 90 days of engagement.

Scoring (last 90 days)::

    reported_phish        +12
    ignored               + 3
    email_opened          - 5
    link_clicked          -12
    credential_submitted  -40

Categories::

    critical_risk : credential_submission_count > 0 OR score < 10
    unaware       : score < 40 OR (clicks >= 2 with no reports in 90d)
    hesitant      : score 40-60 with no reports in 45d
    competent     : score > 60 with >= 1 report in 45d
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import EmailTracking, HumanAsset, PhishingReport

logger = get_logger(__name__)

WINDOW_DAYS = 90
REPORT_WINDOW_DAYS = 45

WEIGHT_REPORTED = 12.0
WEIGHT_IGNORED = 3.0
WEIGHT_OPENED = -5.0
WEIGHT_CLICKED = -12.0
WEIGHT_CREDENTIAL = -40.0

BASE_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

CATEGORY_UNWARE = "unaware"
CATEGORY_HESITANT = "hesitant"
CATEGORY_COMPETENT = "competent"
CATEGORY_CRITICAL = "critical_risk"

CATEGORIES = (CATEGORY_UNWARE, CATEGORY_HESITANT, CATEGORY_COMPETENT, CATEGORY_CRITICAL)


def _now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise a possibly-naive datetime to timezone-aware UTC.

    Args:
        value: The datetime to normalise (``None`` is passed through).

    Returns:
        An aware UTC datetime or ``None``.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ClassificationEngine:
    """Compute and persist employee immunity scores and categories."""

    def __init__(self, window_days: int = WINDOW_DAYS, report_window_days: int = REPORT_WINDOW_DAYS) -> None:
        """Configure the analysis windows.

        Args:
            window_days: Engagement window for scoring.
            report_window_days: Recent-report window used for categorisation.
        """
        self.window_days = window_days
        self.report_window_days = report_window_days

    # ------------------------------------------------------------------ #
    # Data gathering
    # ------------------------------------------------------------------ #
    async def gather_metrics(self, employee_id: uuid.UUID, db: AsyncSession) -> dict[str, float]:
        """Collect the raw counters used by the scoring rules.

        Args:
            employee_id: The employee to analyse.
            db: Active async session.

        Returns:
            A mapping with keys ``opened``, ``clicked``, ``reports_90``,
            ``reports_45``, ``ignored`` and ``credentials``.

        Raises:
            LookupError: If the employee does not exist.
        """
        employee = await db.get(HumanAsset, employee_id)
        if employee is None:
            raise LookupError(f"employee {employee_id} not found")

        now = _now()
        cutoff = now - timedelta(days=self.window_days)
        report_cutoff = now - timedelta(days=self.report_window_days)

        engagement = await db.execute(
            select(
                func.count(EmailTracking.id).filter(EmailTracking.opened_at.is_not(None)),
                func.count(EmailTracking.id).filter(EmailTracking.clicked_at.is_not(None)),
            ).where(
                EmailTracking.employee_id == employee_id,
                EmailTracking.created_at >= cutoff,
            )
        )
        opened, clicked = engagement.one()

        # Reports are counted from the report table (both windows).
        reports_90 = await db.scalar(
            select(func.count(PhishingReport.id)).where(
                PhishingReport.employee_id == employee_id,
                PhishingReport.created_at >= cutoff,
            )
        )
        reports_45 = await db.scalar(
            select(func.count(PhishingReport.id)).where(
                PhishingReport.employee_id == employee_id,
                PhishingReport.created_at >= report_cutoff,
            )
        )

        return {
            "opened": float(opened or 0),
            "clicked": float(clicked or 0),
            "reports_90": float(reports_90 or 0),
            "reports_45": float(reports_45 or 0),
            "ignored": float(employee.total_ignores or 0),
            "credentials": float(employee.total_credential_submissions or 0),
        }

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #
    def score_from_metrics(self, metrics: dict[str, float]) -> float:
        """Compute the immunity score from raw metrics.

        The score starts at ``BASE_SCORE`` (50), applies the weighted rules,
        and is clamped to the ``[0, 100]`` range.

        Args:
            metrics: Output of :meth:`gather_metrics`.

        Returns:
            The rounded score in ``[0, 100]``.
        """
        score = BASE_SCORE
        score += WEIGHT_REPORTED * metrics.get("reports_90", 0.0)
        score += WEIGHT_IGNORED * metrics.get("ignored", 0.0)
        score += WEIGHT_OPENED * metrics.get("opened", 0.0)
        score += WEIGHT_CLICKED * metrics.get("clicked", 0.0)
        score += WEIGHT_CREDENTIAL * metrics.get("credentials", 0.0)
        return round(max(MIN_SCORE, min(MAX_SCORE, score)), 2)

    async def recalculate_score(self, employee_id: uuid.UUID, db: AsyncSession) -> float:
        """Recompute and persist an employee's immunity score.

        Args:
            employee_id: The employee to score.
            db: Active async session (committed by the caller).

        Returns:
            The newly computed score.
        """
        employee = await db.get(HumanAsset, employee_id)
        if employee is None:
            raise LookupError(f"employee {employee_id} not found")
        metrics = await self.gather_metrics(employee_id, db)
        score = self.score_from_metrics(metrics)
        employee.immunity_score = Decimal(str(score))
        await db.flush()
        logger.info("immunity_score_recalculated", employee_id=str(employee_id), score=score)
        return score

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #
    def category_from_metrics(self, metrics: dict[str, float], score: float) -> str:
        """Derive the behavioural category from metrics and score.

        Args:
            metrics: Output of :meth:`gather_metrics`.
            score: The computed immunity score.

        Returns:
            One of ``unaware``, ``hesitant``, ``competent``, ``critical_risk``.
        """
        clicks = metrics.get("clicked", 0.0)
        reports_90 = metrics.get("reports_90", 0.0)
        reports_45 = metrics.get("reports_45", 0.0)
        credentials = metrics.get("credentials", 0.0)

        if credentials > 0 or score < 10:
            return CATEGORY_CRITICAL
        if score < 40 or (clicks >= 2 and reports_90 == 0):
            return CATEGORY_UNWARE
        if score > 60 and reports_45 >= 1:
            return CATEGORY_COMPETENT
        return CATEGORY_HESITANT

    async def classify(self, employee_id: uuid.UUID, db: AsyncSession) -> str:
        """Recompute and persist an employee's score and category.

        Args:
            employee_id: The employee to classify.
            db: Active async session (committed by the caller).

        Returns:
            The new behavioural category.
        """
        employee = await db.get(HumanAsset, employee_id)
        if employee is None:
            raise LookupError(f"employee {employee_id} not found")
        metrics = await self.gather_metrics(employee_id, db)
        score = self.score_from_metrics(metrics)
        category = self.category_from_metrics(metrics, score)
        employee.immunity_score = Decimal(str(score))
        employee.behavioral_category = category
        employee.requires_mandatory_training = category == CATEGORY_UNWARE
        employee.under_enhanced_monitoring = category == CATEGORY_CRITICAL
        await db.flush()
        logger.info(
            "employee_classified",
            employee_id=str(employee_id),
            score=score,
            category=category,
        )
        return category
