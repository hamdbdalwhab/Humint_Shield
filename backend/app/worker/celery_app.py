"""Celery application.

Provides a task queue and beat scheduler for long-running campaign launches
and periodic maintenance.  The broker and result backend are both Redis.

The application is intentionally import-light: the heavy campaign logic lives
in :mod:`app.worker.tasks` and only touches the database inside the task body.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "humint_shield",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=200,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
)

# Database-backed schedules (a periodic re-classification sweep and a
# retention cleanup job).
celery_app.conf.beat_schedule = {
    "reclassify-employees-daily": {
        "task": "app.worker.tasks.reclassify_all_employees",
        "schedule": crontab(hour=2, minute=0),
    },
    "purge-expired-tracking-daily": {
        "task": "app.worker.tasks.purge_expired_tracking",
        "schedule": crontab(hour=3, minute=0),
    },
    "archive-monthly-elo-scores": {
        "task": "app.worker.tasks.archive_monthly_scores",
        "schedule": crontab(hour=23, minute=59),
    },
}


@celery_app.task(name="app.worker.tasks.ping")
def ping() -> str:
    """Return ``pong`` (used by health checks and smoke tests)."""
    return "pong"
