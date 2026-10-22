"""Diagnostic endpoints: deliverability test and dependency health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import User
from app.schemas import TestEmailRequest
from app.services.brevo_email_service import BrevoEmailService

logger = get_logger(__name__)
router = APIRouter(prefix="/test", tags=["diagnostics"])


@router.post(
    "/brevo",
    dependencies=[Depends(rate_limit(limit=5, window=60, scope="test_brevo"))],
    summary="Send a test email through Brevo",
)
async def test_brevo(
    payload: TestEmailRequest,
    user: User = Depends(require_roles("admin", "manager")),
) -> dict:
    """Dispatch a diagnostic email and report the raw result.

    Args:
        payload: Destination address.
        user: Authenticated admin/manager.

    Returns:
        The Brevo response: ``{"success", "message_id", "error"}``.
    """
    logger.info("brevo_test_requested", to=payload.to_email, by=user.username)
    return await BrevoEmailService().send_test_email(payload.to_email)


@router.get("/health", summary="Dependency health check")
async def health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager", "viewer")),
) -> dict:
    """Report the reachability of every external dependency.

    Args:
        db: Active session.
        user: Authenticated user.

    Returns:
        ``{"db", "redis", "brevo_configured", "status"}``.
    """
    settings = get_settings()

    db_ok = False
    db_error = None
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = str(exc)

    redis_ok = False
    redis_error = None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            await client.ping()
            redis_ok = True
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001 - redis is optional
        redis_error = str(exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "db": {"ok": db_ok, "error": db_error},
        "redis": {"ok": redis_ok, "error": redis_error},
        "brevo_configured": settings.brevo_configured,
        "email_dry_run": settings.email_dry_run,
    }


@router.get(
    "/brevo/verify",
    dependencies=[Depends(rate_limit(limit=10, window=60, scope="test_brevo_verify"))],
    summary="Validate the Brevo API key",
)
async def verify_brevo(
    user: User = Depends(require_roles("admin", "manager")),
) -> dict:
    """Call the Brevo account endpoint to validate the API key.

    Args:
        user: Authenticated admin/manager.

    Returns:
        ``{"valid", "error", "detail"}``.
    """
    return await BrevoEmailService().verify_configuration()


@router.get("/config", summary="Non-secret runtime configuration")
async def config_summary(
    user: User = Depends(require_roles("admin", "manager", "viewer")),
) -> dict:
    """Expose the non-secret configuration the UI needs.

    Returns:
        Base URL, sender identity and feature flags.
    """
    settings = get_settings()
    return {
        "base_url": settings.base_url,
        "frontend_url": settings.frontend_url,
        "from_email": settings.from_email,
        "from_name": settings.from_name,
        "email_transport": "smtp" if settings.smtp_transport else "brevo",
        "brevo_configured": settings.brevo_configured,
        "smtp_configured": settings.smtp_configured,
        "email_dry_run": settings.email_dry_run,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "environment": settings.environment,
    }
