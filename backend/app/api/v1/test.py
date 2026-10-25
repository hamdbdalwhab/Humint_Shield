"""Diagnostic endpoints: deliverability test and dependency health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import User
from app.schemas import TestEmailRequest
from app.services.brevo_email_service import BrevoEmailService
from app.services.vonage_service import VonageService

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
        "vonage_configured": settings.vonage_configured,
        "vonage_sms_configured": settings.vonage_sms_configured,
        "vonage_whatsapp_configured": settings.vonage_whatsapp_configured,
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


@router.get(
    "/vonage/verify",
    dependencies=[Depends(rate_limit(limit=20, window=60, scope="test_vonage_verify"))],
    summary="Validate the Vonage SMS/WhatsApp configuration",
)
async def verify_vonage(
    channel: str = Query("sms", pattern="^(sms|whatsapp)$"),
    user: User = Depends(require_roles("admin", "manager")),
) -> dict:
    """Report whether real Vonage delivery is configured for a channel.

    This endpoint deliberately does not send a message.  It validates the
    environment and returns the exact dashboard webhook URLs that must be
    configured for delivery/read receipts.

    Args:
        channel: ``sms`` or ``whatsapp``.
        user: Authenticated admin/manager.

    Returns:
        ``{"valid", "error", "detail", "missing", "webhook_urls", ...}``.
    """
    settings = get_settings()
    service = VonageService(settings=settings)
    status_data = service.configuration_status(channel)
    missing = status_data["missing"]
    base_url = settings.base_url.rstrip("/")
    webhook_urls = {
        "sms_dlr": f"{base_url}/api/v1/webhooks/vonage/dlr",
        "whatsapp_status": f"{base_url}/api/v1/webhooks/vonage/whatsapp-status",
    }
    if status_data["valid"]:
        hint = f"Vonage {channel.upper()} sender '{status_data['from']}' is configured."
        error = None
    else:
        error = (
            "Vonage is not fully configured; set "
            + (", ".join(missing) if missing else "the missing values")
            + " in backend/.env"
        )
        hint = error
    return {
        **status_data,
        "error": error,
        "hint": hint,
        "detail": {
            "transport": "vonage",
            "channel": channel,
            "from": status_data["from"],
            "application_configured": status_data["application_configured"],
            "messages_base_url": status_data["messages_base_url"],
        },
        "sms_ready": settings.vonage_sms_configured,
        "whatsapp_ready": settings.vonage_whatsapp_configured,
        "vonage_configured": settings.vonage_configured,
        "vonage_application_configured": settings.vonage_application_configured,
        "webhook_urls": webhook_urls,
        "webhook_token_required": bool((settings.vonage_webhook_token or "").strip()),
    }


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
        "vonage_configured": settings.vonage_configured,
        "vonage_sms_configured": settings.vonage_sms_configured,
        "vonage_whatsapp_configured": settings.vonage_whatsapp_configured,
        "vonage_application_configured": settings.vonage_application_configured,
        "vonage_sms_from": settings.vonage_sms_from,
        "vonage_whatsapp_from": settings.vonage_whatsapp_from,
        "vonage_webhook_paths": {
            "sms_dlr": "/api/v1/webhooks/vonage/dlr",
            "whatsapp_status": "/api/v1/webhooks/vonage/whatsapp-status",
        },
        "rate_limit_enabled": settings.rate_limit_enabled,
        "environment": settings.environment,
    }
