"""Celery tasks.

Each task opens its own async database session (via
:func:`app.worker.runtime.run_async`) so the synchronous Celery worker process
can safely drive the async ORM.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.logging_config import get_logger
from app.services.campaign_launcher import CampaignLauncher
from app.services.classification_engine import ClassificationEngine
from app.worker.celery_app import celery_app

logger = get_logger(__name__)

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion in a fresh event loop.

    Args:
        coro: The coroutine to execute.

    Returns:
        The coroutine's result.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


@celery_app.task(name="app.worker.tasks.launch_campaign", bind=True, max_retries=0)
def launch_campaign(self, campaign_id: str) -> dict:  # noqa: ANN001
    """Launch a campaign in the background.

    Args:
        campaign_id: The campaign to launch.

    Returns:
        The launcher result dictionary.
    """
    logger.info("task_launch_campaign", campaign_id=campaign_id)

    async def _run() -> dict:
        async with get_session_factory()() as session:
            return await CampaignLauncher().launch_campaign(uuid.UUID(campaign_id), session)

    return run_async(_run())


@celery_app.task(name="app.worker.tasks.reclassify_all_employees")
def reclassify_all_employees() -> dict:
    """Recompute scores and categories for every employee.

    Returns:
        ``{"processed": int, "failed": int}``.
    """
    logger.info("task_reclassify_all_employees")

    async def _run() -> dict:
        from sqlalchemy import select

        from app.models import HumanAsset

        engine = ClassificationEngine()
        processed = 0
        failed = 0
        async with get_session_factory()() as session:
            employee_ids = (
                await session.execute(select(HumanAsset.id))
            ).scalars().all()
            for employee_id in employee_ids:
                try:
                    await engine.classify(employee_id, session)
                    await session.commit()
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    failed += 1
                    logger.warning(
                        "reclassify_failed", employee_id=str(employee_id), error=str(exc)
                    )
        return {"processed": processed, "failed": failed}

    return run_async(_run())


@celery_app.task(name="app.worker.tasks.purge_expired_tracking")
def purge_expired_tracking(retention_days: int | None = None) -> dict:
    """Delete tracking rows older than the retention window.

    Args:
        retention_days: Override for the configured retention period.

    Returns:
        ``{"deleted": int, "retention_days": int}``.
    """
    from sqlalchemy import delete

    from app.config import get_settings
    from app.models import EmailTracking

    days = retention_days or get_settings().data_retention_days
    logger.info("task_purge_expired_tracking", retention_days=days)

    async def _run() -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with get_session_factory()() as session:
            result = await session.execute(
                delete(EmailTracking).where(EmailTracking.created_at < cutoff)
            )
            await session.commit()
            return {"deleted": result.rowcount or 0, "retention_days": days}

    return run_async(_run())


async def execute_retest_failed_employees(
    campaign_id: uuid.UUID | str,
    session: AsyncSession,
) -> dict:
    """Find failed employees from a campaign and create an automated drip re-test campaign.

    Args:
        campaign_id: The campaign ID to check.
        session: Active async database session.

    Returns:
        Status dict with new campaign details or skip reason.
    """
    from sqlalchemy import or_, select
    from app.models import EmailCampaign, EmailTemplate, EmailTracking

    cid = uuid.UUID(str(campaign_id))
    campaign = await session.get(EmailCampaign, cid)
    if campaign is None:
        logger.warning("retest_campaign_not_found", campaign_id=str(campaign_id))
        return {"status": "skipped", "reason": "campaign_not_found"}

    if not getattr(campaign, "auto_retest_failed", False):
        logger.info("retest_disabled_for_campaign", campaign_id=str(campaign_id))
        return {"status": "skipped", "reason": "auto_retest_disabled"}

    # Find all tracking rows for this campaign
    trackings = (
        await session.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == cid)
        )
    ).scalars().all()

    failed_employee_ids: list[uuid.UUID] = []
    for t in trackings:
        has_clicked = t.clicked_at is not None
        has_submitted = (
            t.submitted_at is not None
            or getattr(t, "password_submitted", False)
            or getattr(t, "otp_submitted", False)
        )
        is_safe_or_reported = t.is_reported_safe or (t.reported_at is not None)
        has_completed = t.completed_at is not None

        if has_clicked or has_submitted or (not is_safe_or_reported and not has_completed):
            failed_employee_ids.append(t.employee_id)

    unique_failed_ids = list(dict.fromkeys(failed_employee_ids))
    if not unique_failed_ids:
        logger.info("retest_no_failed_employees", campaign_id=str(campaign_id))
        return {"status": "completed", "targets_count": 0, "message": "No failed employees to retest"}

    orig_template = (
        await session.get(EmailTemplate, campaign.template_id)
        if campaign.template_id
        else None
    )
    curr_diff = orig_template.difficulty_level if orig_template else 5
    channel = campaign.channel or "email"

    # Find higher difficulty template for this channel
    candidate_templates = (
        await session.execute(
            select(EmailTemplate)
            .where(
                or_(
                    EmailTemplate.organization_id == campaign.organization_id,
                    EmailTemplate.is_built_in.is_(True),
                ),
                EmailTemplate.channel == channel,
                EmailTemplate.is_active.is_(True),
                EmailTemplate.difficulty_level > curr_diff,
            )
            .order_by(EmailTemplate.difficulty_level.asc())
        )
    ).scalars().all()

    if candidate_templates:
        selected_template = candidate_templates[0]
    else:
        fallback_templates = (
            await session.execute(
                select(EmailTemplate)
                .where(
                    or_(
                        EmailTemplate.organization_id == campaign.organization_id,
                        EmailTemplate.is_built_in.is_(True),
                    ),
                    EmailTemplate.channel == channel,
                    EmailTemplate.is_active.is_(True),
                )
                .order_by(EmailTemplate.difficulty_level.desc())
            )
        ).scalars().all()
        selected_template = fallback_templates[0] if fallback_templates else orig_template

    new_diff = selected_template.difficulty_level if selected_template else min(10, curr_diff + 1)
    new_campaign_name = f"{campaign.name} - Retest (Automated Drip)"

    new_campaign = EmailCampaign(
        organization_id=campaign.organization_id,
        name=new_campaign_name,
        channel=channel,
        template_id=selected_template.id if selected_template else campaign.template_id,
        channel_config=campaign.channel_config or {},
        target_employee_ids=[str(eid) for eid in unique_failed_ids],
        total_targets=len(unique_failed_ids),
        status="draft",
        auto_retest_failed=False,
        created_by=campaign.created_by,
    )
    session.add(new_campaign)
    await session.flush()

    logger.info(
        "audit_automated_retest_created",
        original_campaign_id=str(campaign.id),
        new_campaign_id=str(new_campaign.id),
        targets_count=len(unique_failed_ids),
        old_difficulty=curr_diff,
        new_difficulty=new_diff,
        template_id=str(new_campaign.template_id),
    )

    await session.commit()
    return {
        "status": "success",
        "new_campaign_id": str(new_campaign.id),
        "targets_count": len(unique_failed_ids),
        "difficulty": new_diff,
    }


@celery_app.task(name="app.worker.tasks.retest_failed_campaign_employees", bind=True, max_retries=0)
def retest_failed_campaign_employees(self, campaign_id: str) -> dict:  # noqa: ANN001
    """Find failed employees from a campaign and launch an automated drip re-test campaign.

    Runs 72 hours after campaign completion.
    Targets only employees who failed (clicked, submitted credentials, or ignored).
    Selects a higher difficulty template and logs the event in the audit trail.
    """
    logger.info("task_retest_failed_campaign_employees", campaign_id=campaign_id)

    async def _run() -> dict:
        async with get_session_factory()() as session:
            return await execute_retest_failed_employees(campaign_id, session)

    return run_async(_run())


@celery_app.task(name="app.worker.tasks.check_smart_alerts")
def check_smart_alerts() -> dict:
    """Evaluate the smart alert rules and log every triggered alert.

    Celery beat runs this hourly.  The rules themselves live in
    :mod:`app.services.alert_service` so the same evaluation can be reused by
    the live dashboard without duplicating thresholds.

    Returns:
        ``{"alerts": <count>, "types": [...]}``.
    """
    logger.info("task_check_smart_alerts")

    async def _run() -> dict:
        from app.services.alert_service import collect_smart_alerts

        async with get_session_factory()() as session:
            alerts = await collect_smart_alerts(session)
        for alert in alerts:
            logger.warning(
                "smart_alert",
                alert_type=alert["type"],
                severity=alert["severity"],
                detail=alert["detail_ar"],
                entity_id=alert["entity_id"],
            )
        return {
            "alerts": len(alerts),
            "types": [alert["type"] for alert in alerts],
        }

    return run_async(_run())


@celery_app.task(name="app.worker.tasks.archive_monthly_scores", bind=True, max_retries=0)
def archive_monthly_scores(
    self, month: str | None = None, force: bool = False
) -> dict:  # noqa: ANN001
    """Archive the current month's Elo scores and reset live scores to 1000.

    Celery beat runs this daily at 23:59 UTC.  The service checks whether the
    day is actually the last day of the month, so every other run is a cheap
    no-op.  ``force=True`` (or an explicit ``month``) is used by the manual
    admin endpoint and local tests.
    """
    logger.info("task_archive_monthly_scores", month=month, force=force)

    async def _run() -> dict:
        from app.services.employee_service import (
            archive_monthly_scores as archive_scores,
        )

        async with get_session_factory()() as session:
            return await archive_scores(
                session, month_year=month, force=force
            )

    return run_async(_run())
