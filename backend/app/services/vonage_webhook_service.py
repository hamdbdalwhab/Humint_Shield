"""Apply Vonage SMS DLR and WhatsApp status callbacks to tracking rows.

The provider callbacks are at-least-once and may arrive out of order.  Updates
therefore never regress a row: a late ``submitted`` callback cannot erase a
``read`` receipt, and duplicate callbacks are harmless.

Matching is deliberately scoped by both ``provider_message_id`` and channel so
an SMS receipt can never mutate a WhatsApp row (or vice versa).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import EmailTracking

logger = get_logger(__name__)

#: Canonical ranks used to prevent status regression.
STATUS_RANK = {
    "submitted": 1,
    "accepted": 2,
    "buffered": 2,
    "delivered": 3,
    "read": 4,
    "failed": 5,
    "rejected": 5,
}

SMS_STATUS_MAP = {
    "submitted": "submitted",
    "accepted": "accepted",
    "buffered": "buffered",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "rejected": "failed",
    "expired": "failed",
    "unknown": "failed",
}

WHATSAPP_STATUS_MAP = {
    "submitted": "submitted",
    "accepted": "accepted",
    "delivered": "delivered",
    "read": "read",
    "rejected": "rejected",
    "failed": "failed",
    "undeliverable": "failed",
    "deleted": "failed",
}

MESSAGE_ID_KEYS = (
    "message_uuid",
    "message-id",
    "message_id",
    "messageId",
    "id",
)
STATUS_KEYS = ("status", "delivery_status", "delivery-status")
TIMESTAMP_KEYS = ("timestamp", "message-timestamp", "message_timestamp", "scts")
ERROR_KEYS = ("error", "error-text", "error_text", "err-code", "reason", "detail")


def _first(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-empty value for ``keys``."""
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _parse_timestamp(value: Any) -> datetime:
    """Parse a provider timestamp, falling back to the current UTC time."""
    if value is not None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = str(value).strip()
        candidates = (text, text.replace("Z", "+00:00"), text.replace(" ", "T"))
        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _error_text(value: Any) -> str | None:
    """Convert a provider error value into a bounded string."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    text = text.strip()
    if not text or text in {"0", "None", "null"}:
        return None
    return text[:500]


class VonageWebhookService:
    """Apply delivery/read receipts to the channel-neutral tracking ledger."""

    def _normalise(self, channel: str, raw_status: Any) -> str | None:
        """Map a provider status to the local canonical status."""
        status = str(raw_status or "").strip().lower()
        mapping = SMS_STATUS_MAP if channel == "sms" else WHATSAPP_STATUS_MAP
        return mapping.get(status)

    async def record_sms_dlr(self, payload: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        """Apply one SMS delivery receipt.

        Args:
            payload: Parsed JSON or form payload from Vonage.
            db: Active session.

        Returns:
            ``{"matched": bool, "message_id", "status", "detail"}``.
        """
        return await self._apply(
            payload,
            db,
            channel="sms",
            source="dlr",
        )

    async def record_whatsapp_status(
        self, payload: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        """Apply one WhatsApp status callback.

        Args:
            payload: Parsed JSON or form payload from Vonage.
            db: Active session.

        Returns:
            ``{"matched": bool, "message_id", "status", "detail"}``.
        """
        return await self._apply(
            payload,
            db,
            channel="whatsapp",
            source="whatsapp_status",
        )

    async def _apply(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        *,
        channel: str,
        source: str,
    ) -> dict[str, Any]:
        """Shared lookup/update path for both provider callbacks."""
        message_id = _first(payload, MESSAGE_ID_KEYS)
        raw_status = _first(payload, STATUS_KEYS)
        if message_id is None:
            logger.warning("vonage_webhook_missing_message_id", source=source)
            return {
                "matched": False,
                "message_id": None,
                "status": None,
                "detail": "missing message id",
            }

        status = self._normalise(channel, raw_status)
        if status is None:
            logger.warning(
                "vonage_webhook_unsupported_status",
                source=source,
                status=str(raw_status),
            )
            return {
                "matched": False,
                "message_id": str(message_id),
                "status": None,
                "detail": f"unsupported status: {raw_status}",
            }

        row = await db.scalar(
            select(EmailTracking)
            .where(
                EmailTracking.provider_message_id == str(message_id),
                EmailTracking.channel == channel,
            )
            .with_for_update()
        )
        if row is None:
            logger.warning(
                "vonage_webhook_unknown_message",
                source=source,
                message_id=str(message_id)[:12],
                channel=channel,
            )
            return {
                "matched": False,
                "message_id": str(message_id),
                "status": status,
                "detail": "tracking row not found",
            }

        occurred_at = _parse_timestamp(_first(payload, TIMESTAMP_KEYS))
        error_text = _error_text(_first(payload, ERROR_KEYS))
        previous = (row.delivery_status or "").strip().lower()
        previous_rank = STATUS_RANK.get(previous, 0)
        new_rank = STATUS_RANK.get(status, 0)
        failed_states = {"failed", "rejected"}

        # A failure is terminal for a real delivery, but a stale failure callback
        # that arrives after a delivered/read receipt must not erase that receipt.
        # Conversely, providers occasionally correct a preliminary failure with a
        # later delivered receipt, so delivered/read may replace a failed state.
        if status in failed_states and previous in {"delivered", "read"}:
            should_apply = False
        elif previous in failed_states and status in {"delivered", "read"}:
            should_apply = True
        else:
            should_apply = new_rank >= previous_rank

        if should_apply:
            row.delivery_status = status
            if status in {"delivered", "read"} and row.delivered_at is None:
                row.delivered_at = occurred_at
            if status == "read" and row.read_at is None:
                row.read_at = occurred_at
            if status in failed_states:
                if row.failed_at is None:
                    row.failed_at = occurred_at
                # Keep the most specific provider error; a duplicate callback
                # without an error body must not overwrite it.
                row.delivery_error = error_text or row.delivery_error or f"Vonage reported {status}"
            else:
                row.failed_at = None
                row.delivery_error = None

        await db.flush()
        logger.info(
            "vonage_webhook_applied",
            source=source,
            message_id=str(message_id)[:12],
            channel=channel,
            status=status,
            previous=previous or None,
            matched=True,
        )
        return {
            "matched": True,
            "message_id": str(message_id),
            "status": status,
            "detail": None,
        }


__all__ = [
    "SMS_STATUS_MAP",
    "STATUS_RANK",
    "WHATSAPP_STATUS_MAP",
    "VonageWebhookService",
]
