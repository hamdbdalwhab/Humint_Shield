"""Tests for the classification engine (all four categories)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTracking, HumanAsset, Organization, PhishingReport
from app.services.classification_engine import (
    CATEGORY_COMPETENT,
    CATEGORY_CRITICAL,
    CATEGORY_HESITANT,
    CATEGORY_UNWARE,
    ClassificationEngine,
)


def _engine() -> ClassificationEngine:
    return ClassificationEngine()


# --------------------------------------------------------------------------- #
# Pure scoring rules
# --------------------------------------------------------------------------- #
def test_base_score_is_fifty() -> None:
    """With no activity the score is the base of 50."""
    assert _engine().score_from_metrics({}) == 50.0


def test_reports_increase_score() -> None:
    """Each report adds 12 points."""
    score = _engine().score_from_metrics({"reports_90": 2.0})
    assert score == 74.0


def test_opens_reduce_score() -> None:
    """Each open subtracts 5 points."""
    assert _engine().score_from_metrics({"opened": 2.0}) == 40.0


def test_clicks_reduce_score() -> None:
    """Each click subtracts 12 points."""
    assert _engine().score_from_metrics({"clicked": 1.0}) == 38.0


def test_ignores_add_score() -> None:
    """Each ignored message adds 3 points."""
    assert _engine().score_from_metrics({"ignored": 4.0}) == 62.0


def test_credentials_heavily_reduce_score() -> None:
    """Each credential submission subtracts 40 points."""
    assert _engine().score_from_metrics({"credentials": 1.0}) == 10.0


def test_score_is_clamped_between_zero_and_hundred() -> None:
    """Scores never leave the ``[0, 100]`` range."""
    engine = _engine()
    assert engine.score_from_metrics({"credentials": 5.0}) == 0.0
    assert engine.score_from_metrics({"reports_90": 20.0}) == 100.0


# --------------------------------------------------------------------------- #
# Category rules
# --------------------------------------------------------------------------- #
def test_category_critical_on_credential_submission() -> None:
    """Any credential submission forces ``critical_risk``."""
    engine = _engine()
    metrics = {"credentials": 1.0, "reports_90": 5.0}
    assert engine.category_from_metrics(metrics, engine.score_from_metrics(metrics)) == (
        CATEGORY_CRITICAL
    )


def test_category_critical_on_low_score() -> None:
    """A score below 10 is critical."""
    engine = _engine()
    metrics = {"credentials": 0.0}
    assert engine.category_from_metrics(metrics, 9.99) == CATEGORY_CRITICAL


def test_category_unaware_on_low_score() -> None:
    """A score below 40 with no credentials is unaware."""
    engine = _engine()
    assert engine.category_from_metrics({"credentials": 0.0}, 30.0) == CATEGORY_UNWARE


def test_category_unaware_on_repeat_clicks_without_reports() -> None:
    """Two or more clicks with no reports makes an employee unaware."""
    engine = _engine()
    metrics = {"clicked": 2.0, "reports_90": 0.0, "credentials": 0.0}
    assert engine.category_from_metrics(metrics, 45.0) == CATEGORY_UNWARE


def test_category_competent_requires_recent_report() -> None:
    """A high score plus a recent report is competent."""
    engine = _engine()
    metrics = {"reports_45": 1.0, "reports_90": 1.0, "credentials": 0.0}
    assert engine.category_from_metrics(metrics, 62.0) == CATEGORY_COMPETENT


def test_category_hesitant_when_score_in_middle() -> None:
    """A middling score with no recent report is hesitant."""
    engine = _engine()
    metrics = {"reports_45": 0.0, "reports_90": 0.0, "credentials": 0.0}
    assert engine.category_from_metrics(metrics, 50.0) == CATEGORY_HESITANT


def test_category_hesitant_without_recent_report() -> None:
    """A high score with only an old report is hesitant."""
    engine = _engine()
    metrics = {"reports_45": 0.0, "reports_90": 2.0, "credentials": 0.0}
    assert engine.category_from_metrics(metrics, 70.0) == CATEGORY_HESITANT


# --------------------------------------------------------------------------- #
# Database-backed metrics
# --------------------------------------------------------------------------- #
async def _campaign_with_tracking(
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    *,
    opened: bool = False,
    clicked: bool = False,
) -> EmailTracking:
    """Create a tracking row with the requested engagement flags."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        name="Classification Campaign",
        status="completed",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
    )
    db.add(campaign)
    await db.flush()
    now = datetime.now(timezone.utc)
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        tracking_uuid=uuid.uuid4(),
        sent_at=now,
        opened_at=now if opened else None,
        clicked_at=now if clicked else None,
    )
    db.add(tracking)
    await db.commit()
    return tracking


async def test_gather_metrics_from_database(
    db: AsyncSession, organization, employee
) -> None:
    """Metrics reflect the tracking rows within the window."""
    await _campaign_with_tracking(db, organization, employee, opened=True, clicked=True)
    metrics = await _engine().gather_metrics(employee.id, db)
    assert metrics["opened"] == 1
    assert metrics["clicked"] == 1
    assert metrics["reports_90"] == 0


async def test_gather_metrics_ignores_old_rows(
    db: AsyncSession, organization, employee
) -> None:
    """Tracking rows older than the window are excluded."""
    tracking = await _campaign_with_tracking(db, organization, employee, opened=True)
    tracking.created_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db.commit()

    metrics = await _engine().gather_metrics(employee.id, db)
    assert metrics["opened"] == 0


async def test_gather_metrics_counts_reports(
    db: AsyncSession, organization, employee
) -> None:
    """Reports inside both windows are counted."""
    for _ in range(2):
        db.add(
            PhishingReport(
                organization_id=organization.id,
                employee_id=employee.id,
                reported_email_subject="Suspicious",
                status="new",
            )
        )
    await db.commit()
    metrics = await _engine().gather_metrics(employee.id, db)
    assert metrics["reports_90"] == 2
    assert metrics["reports_45"] == 2


async def test_gather_metrics_unknown_employee(db: AsyncSession) -> None:
    """An unknown employee raises ``LookupError``."""
    with pytest.raises(LookupError):
        await _engine().gather_metrics(uuid.uuid4(), db)


async def test_recalculate_score_persists(
    db: AsyncSession, organization, employee
) -> None:
    """``recalculate_score`` writes the computed score to the employee."""
    score = await _engine().recalculate_score(employee.id, db)
    await db.commit()
    await db.refresh(employee)
    assert float(employee.immunity_score) == score


async def test_recalculate_score_unknown_employee(db: AsyncSession) -> None:
    """Scoring an unknown employee raises ``LookupError``."""
    with pytest.raises(LookupError):
        await _engine().recalculate_score(uuid.uuid4(), db)


async def test_classify_updates_flags(
    db: AsyncSession, organization, employee
) -> None:
    """Classification persists the category and derived flags."""
    employee.total_credential_submissions = 1
    await db.commit()
    category = await _engine().classify(employee.id, db)
    await db.commit()
    await db.refresh(employee)
    assert category == CATEGORY_CRITICAL
    assert employee.behavioral_category == CATEGORY_CRITICAL
    assert employee.under_enhanced_monitoring is True
    assert employee.requires_mandatory_training is False


async def test_classify_marks_unaware_for_mandatory_training(
    db: AsyncSession, organization, employee
) -> None:
    """Unaware employees are flagged for mandatory training."""
    employee.total_ignores = 0
    employee.total_clicks = 3
    await db.commit()
    for _ in range(3):
        await _campaign_with_tracking(db, organization, employee, clicked=True)
    category = await _engine().classify(employee.id, db)
    await db.commit()
    await db.refresh(employee)
    assert category == CATEGORY_UNWARE
    assert employee.requires_mandatory_training is True


async def test_classify_unknown_employee(db: AsyncSession) -> None:
    """Classifying an unknown employee raises ``LookupError``."""
    with pytest.raises(LookupError):
        await _engine().classify(uuid.uuid4(), db)
