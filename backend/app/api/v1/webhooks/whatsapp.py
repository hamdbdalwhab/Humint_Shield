"""WA-AKG → HUMINT Shield webhook.

The WhatsApp gateway posts engagement events here; this module is the only
writer of ``whatsapp_read``, ``whatsapp_replied`` and
``whatsapp_session_status``.

Supported events (aliases in brackets):

* ``message.received`` (``messages.upsert``) – a recipient replied; the reply is
  classified and scored (negative when information was disclosed, positive when
  the lure was challenged or reported) and only its length/category is stored,
  never the text itself.
* ``message.read`` (``messages.update``) – a read receipt; the tracking row gets
  ``read_at`` and ``delivery_status = "read"``.
* ``connection.update`` (``session.status``) – QR/session state; remembered for
  diagnostics and written to the structured log.

Delivery is best-effort and idempotent: an event for an unknown recipient is
acknowledged with ``handled: false`` (so WA-AKG never retries forever) and a
repeated read receipt does not duplicate ledger rows.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.logging_config import get_logger
from app.deps import require_roles
from app.models import EmailTracking, HumanAsset, User
from app.services.tracking_service import TrackingService
from app.services.whatsapp_service import (
    jid_to_phone,
    normalize_phone,
    record_session_status,
    session_status,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: Event names accepted from WA-AKG, mapped to the three internal kinds.
_EVENT_ALIASES: dict[str, str] = {
    "message.received": "received",
    "message.receive": "received",
    "messages.upsert": "received",
    "message": "received",
    "message.read": "read",
    "messages.update": "read",
    "message.ack": "read",
    "connection.update": "connection",
    "session.status": "connection",
    "session.update": "connection",
}


def _extract_event(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return ``(internal_kind, data)`` from a WA-AKG webhook payload."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw_event = (
        payload.get("event")
        or payload.get("type")
        or payload.get("webhookEvent")
        or (data.get("event") if isinstance(data, dict) else None)
        or ""
    )
    event = str(raw_event).strip().lower().replace("_", ".")
    kind = _EVENT_ALIASES.get(event, "unknown")
    if kind == "unknown" and event:
        if event.startswith("message") and "read" in event:
            kind = "read"
        elif event.startswith("connection") or event.startswith("session"):
            kind = "connection"
    return kind, data if isinstance(data, dict) else {}


def _extract_message_id(data: dict[str, Any]) -> str | None:
    """Return the WhatsApp message id from any supported payload shape."""
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    inner_key = message.get("key") if isinstance(message.get("key"), dict) else {}
    for candidate in (
        data.get("messageId"),
        data.get("message_id"),
        data.get("id"),
        key.get("id"),
        inner_key.get("id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _extract_sender_jid(data: dict[str, Any]) -> str | None:
    """Return the sender JID from a received-message payload."""
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    for candidate in (
        data.get("from"),
        data.get("sender"),
        data.get("remoteJid"),
        key.get("remoteJid"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _extract_reply_text(data: dict[str, Any]) -> str:
    """Return the reply body from any supported payload shape."""
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    candidates = (
        message.get("conversation"),
        (message.get("extendedTextMessage") or {}).get("text")
        if isinstance(message.get("extendedTextMessage"), dict)
        else None,
        data.get("text"),
        data.get("body"),
        data.get("message"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


async def _find_whatsapp_tracking(
    db: AsyncSession,
    *,
    message_id: str | None,
    phone: str | None,
) -> EmailTracking | None:
    """Return the tracking row a receipt/reply belongs to."""
    if message_id:
        row = await db.scalar(
            select(EmailTracking)
            .where(
                EmailTracking.provider_message_id == message_id,
                EmailTracking.channel == "whatsapp",
            )
            .order_by(EmailTracking.sent_at.desc())
            .limit(1)
        )
        if row is not None:
            return row
    digits = normalize_phone(phone)
    if not digits:
        return None
    employee = await db.scalar(
        select(HumanAsset).where(
            or_(HumanAsset.phone == f"+{digits}", HumanAsset.phone == digits)
        )
    )
    if employee is None:
        # Numbers are entered by hand in the UI, so fall back to a normalised
        # comparison instead of failing on "+967 77 000 0000" style values.
        for candidate in (await db.execute(select(HumanAsset))).scalars():
            if candidate.phone and normalize_phone(candidate.phone) == digits:
                employee = candidate
                break
    if employee is None:
        return None
    return await db.scalar(
        select(EmailTracking)
        .where(
            EmailTracking.employee_id == employee.id,
            EmailTracking.channel == "whatsapp",
        )
        .order_by(EmailTracking.sent_at.desc())
        .limit(1)
    )


@router.post(
    "/whatsapp",
    summary="WA-AKG webhook (read receipts, replies, session state)",
)
async def whatsapp_webhook(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Handle one WA-AKG webhook delivery.

    When ``WA_AKG_WEBHOOK_SECRET`` is set, the gateway must send the same value
    in ``X-Webhook-Token`` (or ``Authorization: Bearer …``).  A wrong token is
    rejected with 401 so a stranger cannot forge read receipts.

    Returns:
        ``{"ok", "event", "handled", "detail"}`` — always 200 for a valid body,
        so the gateway stops retrying events this installation cannot match.
    """
    settings = get_settings()
    secret = (settings.wa_akg_webhook_secret or "").strip()
    if secret:
        auth = request.headers.get("authorization") or ""
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if secret not in {(x_webhook_token or "").strip(), bearer}:
            logger.warning("whatsapp_webhook_unauthorized")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid webhook token",
            )
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook body must be a JSON object",
        )

    kind, data = _extract_event(payload)
    session_id = str(
        payload.get("sessionId")
        or payload.get("session_id")
        or data.get("sessionId")
        or data.get("session_id")
        or settings.wa_akg_session_id
        or ""
    ).strip() or None

    if kind == "connection":
        state = (
            data.get("state")
            or data.get("status")
            or data.get("connection")
            or payload.get("state")
            or "unknown"
        )
        record_session_status(session_id, str(state), {"raw": data})
        return {
            "ok": True,
            "event": "connection.update",
            "handled": True,
            "detail": {"session_id": session_id, "status": str(state)},
        }

    message_id = _extract_message_id(data)
    sender = _extract_sender_jid(data)
    phone = jid_to_phone(sender) if sender else None
    tracking = await _find_whatsapp_tracking(db, message_id=message_id, phone=phone)
    if tracking is None:
        logger.info(
            "whatsapp_webhook_unmatched",
            webhook_event=kind,
            message_id=message_id,
            phone=phone,
        )
        return {
            "ok": True,
            "event": f"message.{kind}" if kind != "unknown" else "unknown",
            "handled": False,
            "detail": {"reason": "no matching WhatsApp tracking row"},
        }

    service = TrackingService()
    if kind == "read":
        if tracking.read_at is not None:
            return {
                "ok": True,
                "event": "message.read",
                "handled": True,
                "detail": {"duplicate": True, "tracking_uuid": str(tracking.tracking_uuid)},
            }
        await service.log_whatsapp_read(
            tracking.tracking_uuid, db, message_id=message_id
        )
        await db.commit()
        return {
            "ok": True,
            "event": "message.read",
            "handled": True,
            "detail": {"tracking_uuid": str(tracking.tracking_uuid)},
        }

    if kind == "received":
        text = _extract_reply_text(data)
        outcome = await service.log_whatsapp_reply(
            tracking.tracking_uuid,
            db,
            text=text,
            phone=phone,
            message_id=message_id,
        )
        await db.commit()
        detail: dict[str, Any] = {"tracking_uuid": str(tracking.tracking_uuid)}
        if outcome is not None:
            _, category, delta = outcome
            detail.update({"category": category, "elo_delta": delta})
        return {
            "ok": True,
            "event": "message.received",
            "handled": True,
            "detail": detail,
        }

    logger.info("whatsapp_webhook_ignored", webhook_event=kind)
    return {
        "ok": True,
        "event": "unknown",
        "handled": False,
        "detail": {"reason": "unsupported event"},
    }


@router.get(
    "/whatsapp/status",
    summary="Last reported WA-AKG session state",
)
async def whatsapp_webhook_status(
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Return the last ``connection.update`` this process received.

    Authenticated: the payload names the missing environment variables and the
    gateway session state, which is operator-only diagnostics information.
    """
    settings = get_settings()
    state = session_status(settings.wa_akg_session_id)
    return {
        "ok": True,
        "configured": settings.whatsapp_configured,
        "missing": settings.whatsapp_missing_settings(),
        "session": state,
    }
