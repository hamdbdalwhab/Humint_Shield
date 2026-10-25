"""Unauthenticated Vonage delivery/read receipt webhooks.

Vonage must be able to reach these endpoints without a dashboard session.  When
``VONAGE_WEBHOOK_TOKEN`` is configured, the exact same value must be supplied
either as the ``token`` query parameter, ``X-Vonage-Webhook-Token`` header, or
an ``Authorization: Bearer ...`` header.  Configure the resulting URLs in the
Vonage dashboard:

* SMS DLR:     ``/api/v1/webhooks/vonage/dlr?token=...``
* WhatsApp:    ``/api/v1/webhooks/vonage/whatsapp-status?token=...``
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.logging_config import get_logger
from app.services.vonage_webhook_service import VonageWebhookService

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks/vonage", tags=["webhooks"])


def _supplied_token(request: Request) -> str | None:
    """Extract a webhook token from the query string or supported headers."""
    token = request.query_params.get("token")
    if token:
        return token
    header = request.headers.get("x-vonage-webhook-token")
    if header:
        return header
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def verify_webhook_token(request: Request) -> None:
    """Reject callbacks that do not carry the configured shared token.

    When ``VONAGE_WEBHOOK_TOKEN`` is empty, verification is intentionally
    disabled so local development and the Vonage sandbox can be wired quickly.
    Production deployments should always set a long random token.
    """
    expected = (get_settings().vonage_webhook_token or "").strip()
    if not expected:
        return
    supplied = _supplied_token(request)
    if not supplied or not secrets.compare_digest(supplied, expected):
        logger.warning(
            "vonage_webhook_token_rejected",
            client=request.client.host if request.client else None,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Vonage webhook token",
        )


async def _read_payload(request: Request) -> dict[str, Any]:
    """Read a JSON or form-encoded Vonage callback into a flat mapping."""
    payload: dict[str, Any] = dict(request.query_params)
    if request.method.upper() == "GET":
        return payload

    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001 - malformed provider payload
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON webhook body: {exc}",
            ) from exc
        if isinstance(body, dict):
            payload.update(body)
        return payload

    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 - malformed provider payload
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid form webhook body: {exc}",
        ) from exc
    for key, value in form.multi_items():
        if isinstance(value, str):
            payload[key] = value
    return payload


async def _handle(
    request: Request,
    db: AsyncSession,
    *,
    channel: str,
) -> dict[str, Any]:
    """Parse and apply one callback, committing the tracking update."""
    payload = await _read_payload(request)
    service = VonageWebhookService()
    try:
        if channel == "sms":
            result = await service.record_sms_dlr(payload, db)
        else:
            result = await service.record_whatsapp_status(payload, db)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - never leak provider internals
        await db.rollback()
        logger.error(
            "vonage_webhook_failed",
            channel=channel,
            error=str(exc),
        )
        # 500 makes Vonage retry; the update is idempotent when it succeeds.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to apply Vonage webhook",
        ) from exc
    return {
        "received": True,
        "channel": channel,
        **result,
    }


@router.post("/dlr", summary="Receive a Vonage SMS delivery receipt")
async def vonage_sms_dlr(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_webhook_token),
) -> dict[str, Any]:
    """Apply a Vonage SMS DLR (JSON or form encoded, GET also supported)."""
    return await _handle(request, db, channel="sms")


@router.get("/dlr", summary="Receive a Vonage SMS delivery receipt (GET)")
async def vonage_sms_dlr_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_webhook_token),
) -> dict[str, Any]:
    """Accept DLR callbacks from providers configured for HTTP GET."""
    return await _handle(request, db, channel="sms")


@router.post("/whatsapp-status", summary="Receive a Vonage WhatsApp status callback")
async def vonage_whatsapp_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_webhook_token),
) -> dict[str, Any]:
    """Apply submitted/delivered/read/rejected WhatsApp status updates."""
    return await _handle(request, db, channel="whatsapp")
