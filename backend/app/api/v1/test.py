"""Diagnostic endpoints: deliverability test and dependency health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_permissions
from app.logging_config import get_logger
from app.models import User
from app.schemas import TestEmailRequest
from app.services.brevo_email_service import BrevoEmailService
from app.services.illyvoip_service import IllyVoIPService
from app.services.textbee_service import TextBeeService

logger = get_logger(__name__)
router = APIRouter(prefix="/test", tags=["diagnostics"])


def _illyvoip_identity() -> dict[str, str | None]:
    """Return the effective SIP identity and caller ID, or ``None``.

    Placeholder values (``CHANGE_ME_…``, ``YOUR_…``) are reported as unset so
    the UI never presents them as a real caller ID.
    """
    status = IllyVoIPService().configuration_status()
    return {
        "illyvoip_sip_user_id": status.get("sip_user_id"),
        "illyvoip_caller_id": status.get("caller_id"),
    }


@router.post(
    "/brevo",
    dependencies=[Depends(rate_limit(limit=5, window=60, scope="test_brevo"))],
    summary="Send a test email through Brevo",
)
async def test_brevo(
    payload: TestEmailRequest,
    user: User = Depends(require_permissions("settings.diagnostics")),
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
    user: User = Depends(require_permissions("settings.view")),
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
        "textbee_configured": settings.textbee_configured,
        "sms_provider": settings.sms_provider_effective,
        "illyvoip_configured": settings.illyvoip_configured,
        "illyvoip_api_key_configured": settings.illyvoip_api_key_configured,
        "illyvoip_missing_settings": settings.illyvoip_missing_settings(),
        "illyvoip_identity_warnings": settings.illyvoip_identity_warnings(),
    }


@router.get(
    "/illyvoip/verify",
    dependencies=[Depends(rate_limit(limit=10, window=60, scope="test_illyvoip_verify"))],
    summary="Validate the IllyVoIP Voice API configuration",
)
async def verify_illyvoip(
    user: User = Depends(require_permissions("settings.diagnostics")),
) -> dict:
    """Validate local readiness and the live IllyVoIP Voice backend.

    This endpoint never places a call.  It returns the non-secret readiness
    report plus the provider's ``backend_status``.

    Args:
        user: Authenticated admin/manager.

    Returns:
        ``{"valid", "missing", "api_reachable", "backend_status", ...}``.
    """
    return await IllyVoIPService().verify_configuration()


@router.get(
    "/brevo/verify",
    dependencies=[Depends(rate_limit(limit=10, window=60, scope="test_brevo_verify"))],
    summary="Validate the Brevo API key",
)
async def verify_brevo(
    user: User = Depends(require_permissions("settings.diagnostics")),
) -> dict:
    """Call the Brevo account endpoint to validate the API key.

    Args:
        user: Authenticated admin/manager.

    Returns:
        ``{"valid", "error", "detail"}``.
    """
    return await BrevoEmailService().verify_configuration()


@router.get(
    "/sms/verify",
    dependencies=[Depends(rate_limit(limit=20, window=60, scope="test_sms_verify"))],
    summary="Validate the TextBee SMS gateway configuration",
)
async def verify_sms(
    user: User = Depends(require_permissions("settings.diagnostics")),
) -> dict:
    """Report whether real SMS delivery through TextBee can work.

    This endpoint deliberately does not send a message.  It validates the
    environment and, when a key is present, asks TextBee to confirm it.

    Args:
        user: Authenticated admin/manager.

    Returns:
        ``{"valid", "error", "hint", "missing", "provider", ...}``.
    """
    settings = get_settings()
    service = TextBeeService(settings=settings)
    status_data = await service.verify_configuration()
    missing = status_data.get("missing") or []
    if status_data.get("valid"):
        hint = (
            "TextBee SMS gateway is ready"
            + (
                f" (device {status_data.get('device_id')})."
                if status_data.get("device_id")
                else "."
            )
        )
        error = None
    else:
        error = status_data.get("error") or (
            "TextBee is not fully configured; set "
            + (", ".join(missing) if missing else "TEXTBEE_API_KEY")
            + " in backend/.env"
        )
        hint = error
    return {
        **status_data,
        "provider": "textbee",
        "channel": "sms",
        "error": error,
        "hint": hint,
        "sms_ready": bool(status_data.get("valid")),
        "whatsapp_ready": False,
    }


@router.get("/config", summary="Non-secret runtime configuration")
async def config_summary(
    user: User = Depends(require_permissions("settings.view")),
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
        "textbee_configured": settings.textbee_configured,
        "textbee_device_id": settings.textbee_device_id or None,
        "textbee_missing_settings": settings.textbee_missing_settings(),
        "sms_provider": settings.sms_provider_effective,
        "illyvoip_configured": settings.illyvoip_configured,
        "illyvoip_api_key_configured": settings.illyvoip_api_key_configured,
        "illyvoip_missing_settings": settings.illyvoip_missing_settings(),
        "illyvoip_identity_warnings": settings.illyvoip_identity_warnings(),
        **_illyvoip_identity(),
        "illyvoip_tts_language": settings.illyvoip_tts_language,
        "illyvoip_tts_voice": settings.illyvoip_tts_voice,
        "illyvoip_record_calls": settings.illyvoip_record_calls,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "environment": settings.environment,
    }
