"""Real WhatsApp delivery through a self-hosted WA-AKG gateway.

WA-AKG (https://github.com/rmyndharis/wa-akg) runs a WhatsApp Web session in a
container and exposes a REST API in front of it.  This module is the only place
that talks to that API.

Contract (as configured by the operator):

* ``POST {WA_AKG_API_URL}/messages/{WA_AKG_SESSION_ID}/{jid}/send``;
* ``Authorization: Bearer {WA_AKG_API_KEY}`` from the server only;
* JSON body ``{"message": "..."}``;
* ``jid`` is ``{phone}@s.whatsapp.net`` (individual chat).

**HTTP 200/201 means handed to the WhatsApp session**, not delivered and not
read.  Delivery/read receipts arrive asynchronously through the webhook
(``/api/v1/webhooks/whatsapp``), which is the only source of ``read`` and
``replied`` states — exactly like the TextBee device confirms SMS delivery.

``send_whatsapp_message`` never raises: transports failures are returned as a
result dictionary so one unreachable recipient can never abort a campaign.
"""
from __future__ import annotations

import asyncio
import random
import re
import uuid
from typing import Any, Awaitable, Callable, Iterable

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Domain part of a WhatsApp individual chat JID.
JID_DOMAIN = "s.whatsapp.net"

#: Delivered-length budget for one WhatsApp message (wizard hard limit).
MAX_MESSAGE_LENGTH = 170

#: Default anti-ban pacing (seconds) when the settings are unusable.
DEFAULT_MIN_DELAY = 10.0
DEFAULT_MAX_DELAY = 30.0

#: ``{phone}`` placeholders the operator may use inside a WhatsApp template.
LINK_PLACEHOLDERS = ("{{link}}", "{link}", "[link]")

_PHONE_DIGITS_RE = re.compile(r"\D+")

#: Last ``connection.update`` seen per session (process-local, best effort).
_SESSION_STATE: dict[str, dict[str, Any]] = {}


class WhatsAppError(RuntimeError):
    """Base class for WA-AKG failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.retry_after = retry_after


class WhatsAppConfigurationError(WhatsAppError):
    """Raised when WA-AKG credentials are missing."""


class WhatsAppSendError(WhatsAppError):
    """Raised when WA-AKG rejects a message."""


class WhatsAppSessionDisconnected(WhatsAppSendError):
    """The WhatsApp session is not connected (QR not scanned / logged out)."""


class WhatsAppInvalidNumber(WhatsAppSendError):
    """The recipient has no WhatsApp account / the JID is malformed."""


class WhatsAppRateLimited(WhatsAppSendError):
    """The gateway (or WhatsApp) is throttling the session."""


def normalize_phone(value: str | None) -> str:
    """Return the digits of a phone number, without ``+`` or separators."""
    return _PHONE_DIGITS_RE.sub("", (value or "").strip())


def is_whatsapp_phone(value: str | None) -> bool:
    """Return ``True`` for a plausible E.164 number (8-15 digits)."""
    digits = normalize_phone(value)
    return 8 <= len(digits) <= 15 and not digits.startswith("0")


def format_jid(phone: str | None) -> str:
    """Return ``{digits}@s.whatsapp.net`` for a phone number.

    Raises:
        WhatsAppInvalidNumber: When the number cannot form a valid JID.
    """
    digits = normalize_phone(phone)
    if not is_whatsapp_phone(digits):
        raise WhatsAppInvalidNumber(
            f"'{phone}' is not a valid WhatsApp number; use an E.164 number "
            "such as +966500000000",
            error_code="invalid_recipient",
        )
    return f"{digits}@{JID_DOMAIN}"


def mask_phone(value: str | None) -> str:
    """Return a non-secret rendering of a phone number."""
    digits = normalize_phone(value)
    if len(digits) <= 6:
        return "***"
    return f"{digits[:4]}***{digits[-2:]}"


def jid_to_phone(jid: str | None) -> str:
    """Return the digits of a JID such as ``9677...@s.whatsapp.net``."""
    value = (jid or "").strip()
    if not value:
        return ""
    return normalize_phone(value.split("@", 1)[0])


def inject_tracking_link(
    template_text: str, tracking_uuid: uuid.UUID | str, base_url: str | None = None
) -> str:
    """Return the message body with the per-recipient tracking link filled in.

    ``{{link}}`` is replaced everywhere it appears; a body without any
    placeholder gets the link appended, so no message is ever sent silently
    without its tracking URL.
    """
    settings = get_settings()
    root = (base_url or settings.base_url or "").strip().rstrip("/")
    link = f"{root}/api/v1/track/whatsapp/{tracking_uuid}"
    body = template_text or ""
    if any(placeholder in body for placeholder in LINK_PLACEHOLDERS):
        for placeholder in LINK_PLACEHOLDERS:
            body = body.replace(placeholder, link)
        return body
    return f"{body.rstrip()}\n{link}" if body.strip() else link


def record_session_status(
    session_id: str | None, status: str | None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Remember the last ``connection.update`` state and log it.

    The gateway does not persist its session state for us, and there is no
    settings table in this schema, so the newest state is kept in memory for the
    diagnostics endpoint and always written to the structured log.
    """
    entry = {
        "session_id": (session_id or "").strip() or None,
        "status": (status or "unknown").strip().lower(),
        "details": details or {},
    }
    if entry["session_id"]:
        _SESSION_STATE[entry["session_id"]] = entry
    _SESSION_STATE["__latest__"] = entry
    logger.info(
        "whatsapp_session_status",
        session_id=entry["session_id"],
        status=entry["status"],
    )
    return entry


def session_status(session_id: str | None = None) -> dict[str, Any] | None:
    """Return the last known session state (``None`` when never reported)."""
    key = (session_id or "").strip()
    if key:
        return _SESSION_STATE.get(key)
    return _SESSION_STATE.get("__latest__")


class WhatsAppService:
    """Client for the WA-AKG WhatsApp gateway."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            settings: Optional settings override (tests).
            client: Optional injected HTTP client (tests).
        """
        self.settings = settings or get_settings()
        self._client = client
        self._base_url = (self.settings.wa_akg_api_url or "").strip().rstrip("/")

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def configuration_status(self) -> dict[str, Any]:
        """Return non-secret readiness for the WhatsApp channel."""
        missing = self.settings.whatsapp_missing_settings()
        return {
            "provider": "wa-akg",
            "valid": not missing,
            "configured": self.settings.whatsapp_configured,
            "base_url": self._base_url or None,
            "session_id": (self.settings.wa_akg_session_id or "").strip() or None,
            # The key itself is never returned, only whether it is present.
            "api_key_set": self.settings.wa_akg_api_key_configured,
            "missing": missing,
        }

    def _require_configured(self) -> None:
        missing = self.settings.whatsapp_missing_settings()
        if missing:
            raise WhatsAppConfigurationError(
                "WhatsApp (WA-AKG) is not configured; set "
                + ", ".join(missing)
                + " in backend/.env"
            )

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {(self.settings.wa_akg_api_key or '').strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _send_url(self, jid: str) -> str:
        session = (self.settings.wa_akg_session_id or "").strip()
        return f"{self._base_url}/messages/{session}/{jid}/send"

    def _classify_failure(
        self, status_code: int, payload: Any, retry_after: float | None
    ) -> WhatsAppSendError:
        """Map a WA-AKG error response to a typed exception."""
        message = ""
        error_code = None
        if isinstance(payload, dict):
            message = str(
                payload.get("message")
                or payload.get("error")
                or payload.get("detail")
                or ""
            )
            error_code = payload.get("code") or payload.get("errorCode")
        lowered = message.lower()
        detail = message or f"WA-AKG returned HTTP {status_code}"
        if status_code in (401, 403) or ("session" in lowered and "connect" in lowered):
            return WhatsAppSessionDisconnected(
                detail or "the WhatsApp session is not connected",
                status_code=status_code,
                error_code="session_disconnected",
            )
        if status_code == 429:
            return WhatsAppRateLimited(
                detail,
                status_code=status_code,
                error_code="rate_limited",
                retryable=True,
                retry_after=retry_after,
            )
        if status_code in (400, 404, 422) and (
            "not on whatsapp" in lowered
            or "not registered" in lowered
            or "invalid" in lowered
            or "no lid" in lowered
            or not message
        ):
            return WhatsAppInvalidNumber(
                detail,
                status_code=status_code,
                error_code="invalid_number",
            )
        return WhatsAppSendError(
            detail,
            status_code=status_code,
            error_code=str(error_code) if error_code else "provider_error",
            retryable=status_code >= 500,
        )

    async def _post_message(self, jid: str, body: str) -> dict[str, Any]:
        """POST one message and return the decoded envelope.

        Raises:
            WhatsAppConfigurationError: Missing credentials.
            WhatsAppSendError: Any transport or provider failure.
        """
        self._require_configured()
        url = self._send_url(jid)
        timeout = httpx.Timeout(float(self.settings.wa_akg_timeout_seconds or 25.0))
        try:
            if self._client is not None:
                response = await self._client.post(
                    url, json={"message": body}, headers=self._headers()
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        url, json={"message": body}, headers=self._headers()
                    )
        except httpx.TimeoutException as exc:
            raise WhatsAppSendError(
                "WA-AKG send timed out",
                error_code="timeout",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(
                f"WA-AKG transport error: {exc}",
                error_code="transport_error",
                retryable=True,
            ) from exc

        try:
            payload: Any = response.json()
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            retry_after = None
            raw_retry = response.headers.get("retry-after")
            if raw_retry:
                try:
                    retry_after = float(raw_retry)
                except ValueError:
                    retry_after = None
            raise self._classify_failure(response.status_code, payload, retry_after)
        return payload if isinstance(payload, dict) else {"data": payload}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def send_whatsapp_message(
        self,
        to_phone: str,
        message: str,
        tracking_uuid: uuid.UUID | str | None = None,
    ) -> dict[str, Any]:
        """Send one WhatsApp message and describe the outcome.

        Args:
            to_phone: Recipient in E.164 format (``+967770447622``).
            message: Message body, already personalised.
            tracking_uuid: Per-recipient tracking UUID, used for logging and for
                the ``{{link}}`` placeholder when the body still contains it.

        Returns:
            ``{"success", "provider", "message_id", "jid", "status_code",
            "error", "error_code", "retryable", "raw"}``.  Never raises.
        """
        result: dict[str, Any] = {
            "success": False,
            "provider": "wa-akg",
            "message_id": None,
            "jid": None,
            "status_code": None,
            "error": None,
            "error_code": None,
            "retryable": False,
            "raw": None,
        }
        body = (message or "").strip()
        if tracking_uuid is not None and any(
            placeholder in body for placeholder in LINK_PLACEHOLDERS
        ):
            body = inject_tracking_link(body, tracking_uuid)
        if not body:
            result.update(error="message cannot be empty", error_code="empty_message")
            return result
        if len(body) > MAX_MESSAGE_LENGTH:
            # WhatsApp accepts longer bodies, but the wizard guarantees one
            # 170-character screen.  Log it instead of truncating a lure.
            logger.warning(
                "whatsapp_message_over_budget",
                to=mask_phone(to_phone),
                characters=len(body),
                limit=MAX_MESSAGE_LENGTH,
            )
        try:
            jid = format_jid(to_phone)
        except WhatsAppInvalidNumber as exc:
            result.update(error=str(exc), error_code=exc.error_code)
            return result
        result["jid"] = jid

        try:
            payload = await self._post_message(jid, body)
        except WhatsAppError as exc:
            result.update(
                error=str(exc),
                error_code=exc.error_code or "whatsapp_error",
                status_code=exc.status_code,
                retryable=exc.retryable,
            )
            logger.warning(
                "whatsapp_send_failed",
                to=mask_phone(to_phone),
                error_code=exc.error_code,
                status_code=exc.status_code,
            )
            return result

        envelope = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        key = envelope.get("key")
        message_id = (
            envelope.get("id")
            or envelope.get("messageId")
            or envelope.get("message_id")
            or (key.get("id") if isinstance(key, dict) else None)
            or payload.get("id")
            or payload.get("messageId")
        )
        result.update(
            success=True,
            message_id=str(message_id) if message_id else None,
            raw=envelope,
        )
        logger.info(
            "whatsapp_sent",
            to=mask_phone(to_phone),
            jid=jid,
            message_id=result["message_id"],
            tracking_uuid=str(tracking_uuid) if tracking_uuid else None,
            characters=len(body),
        )
        return result

    def delay_between_messages(self) -> float:
        """Return the anti-ban pause (seconds) before the next message."""
        try:
            low = float(self.settings.wa_akg_min_delay_seconds)
        except (TypeError, ValueError):
            low = DEFAULT_MIN_DELAY
        try:
            high = float(self.settings.wa_akg_max_delay_seconds)
        except (TypeError, ValueError):
            high = DEFAULT_MAX_DELAY
        low = max(0.0, low)
        high = max(low, high)
        return random.uniform(low, high)

    async def send_whatsapp_broadcast(
        self,
        employees: Iterable[Any],
        template_text: str,
        campaign_id: uuid.UUID | str,
        *,
        base_url: str | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        on_sent: Callable[[Any, uuid.UUID, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Send a WhatsApp broadcast to ``employees`` with anti-ban pacing.

        Each recipient gets a fresh ``tracking_uuid`` and the matching
        ``/api/v1/track/whatsapp/{uuid}`` link injected into the body.  A random
        pause of ``WA_AKG_MIN_DELAY_SECONDS``-``WA_AKG_MAX_DELAY_SECONDS`` is
        applied before every message after the first, and a throttled message
        (HTTP 429) is retried once after the provider's ``Retry-After``.

        Args:
            employees: Objects with ``phone`` (and optionally ``full_name``).
            template_text: Body template; ``{{link}}`` marks the tracker.
            campaign_id: Campaign the batch belongs to (logging only).
            base_url: Public origin used to build the tracking link.
            sleep: Injectable asyncio.sleep (tests).
            on_sent: Optional callback after each successful send, typically the
                ledger writer for ``whatsapp_sent``.

        Returns:
            ``{"campaign_id", "total", "sent", "failed", "results"}``.
        """
        pause = sleep or asyncio.sleep
        rows = list(employees)
        results: list[dict[str, Any]] = []
        sent = 0
        failed = 0
        for index, employee in enumerate(rows):
            if index > 0:
                delay = self.delay_between_messages()
                logger.info("whatsapp_broadcast_pause", seconds=round(delay, 1))
                await pause(delay)
            tracking_uuid = uuid.uuid4()
            phone = getattr(employee, "phone", None)
            body = inject_tracking_link(template_text or "", tracking_uuid, base_url)
            outcome = await self.send_whatsapp_message(phone or "", body, tracking_uuid)
            if not outcome.get("success") and outcome.get("error_code") == "rate_limited":
                retry_after = min(float(outcome.get("retry_after") or 30.0), 120.0)
                logger.warning("whatsapp_broadcast_throttled", retry_after=retry_after)
                await pause(retry_after)
                outcome = await self.send_whatsapp_message(phone or "", body, tracking_uuid)
            results.append(
                {
                    "employee_id": str(getattr(employee, "id", "") or "") or None,
                    "tracking_uuid": str(tracking_uuid),
                    **outcome,
                }
            )
            if outcome.get("success"):
                sent += 1
                if on_sent is not None:
                    try:
                        await on_sent(employee, tracking_uuid, outcome)
                    except Exception:  # noqa: BLE001 - the message is already sent
                        logger.exception(
                            "whatsapp_broadcast_callback_failed",
                            tracking_uuid=str(tracking_uuid),
                        )
            else:
                failed += 1
        logger.info(
            "whatsapp_broadcast_completed",
            campaign_id=str(campaign_id),
            total=len(rows),
            sent=sent,
            failed=failed,
        )
        return {
            "campaign_id": str(campaign_id),
            "total": len(rows),
            "sent": sent,
            "failed": failed,
            "results": results,
        }


__all__ = [
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MIN_DELAY",
    "JID_DOMAIN",
    "LINK_PLACEHOLDERS",
    "MAX_MESSAGE_LENGTH",
    "WhatsAppConfigurationError",
    "WhatsAppError",
    "WhatsAppInvalidNumber",
    "WhatsAppRateLimited",
    "WhatsAppSendError",
    "WhatsAppService",
    "WhatsAppSessionDisconnected",
    "format_jid",
    "inject_tracking_link",
    "is_whatsapp_phone",
    "jid_to_phone",
    "mask_phone",
    "normalize_phone",
    "record_session_status",
    "session_status",
]
