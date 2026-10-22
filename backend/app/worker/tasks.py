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
