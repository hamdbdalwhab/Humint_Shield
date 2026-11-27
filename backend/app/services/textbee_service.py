"""Real SMS delivery through the TextBee gateway (https://textbee.dev).

TextBee sends SMS through an Android phone registered to the account: the API
pushes the message to the device and the phone's SIM transmits it.  This module
is the only place that talks to TextBee.

Contract notes (verified against https://textbee.dev/docs/sending-sms):

* base URL ``https://api.textbee.dev/api/v1``;
* authentication is the ``x-api-key`` header, sent from the server only;
* ``POST /gateway/send-sms`` with ``{"recipients": [...], "message": "...",
  "deviceId": "..."}`` queues the message and returns an ``smsBatchId``;
* **HTTP 200 means queued, not delivered**; delivery is confirmed through the
  message/batch endpoints or the signed webhook;
* errors: ``401`` bad key, ``400`` invalid request/device, ``429`` plan limit.

``send_sms`` never raises: it returns the success/failure dictionary the
campaign launcher persists, so one failed recipient can never abort a batch.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.services.sms_segments import segment_info

logger = get_logger(__name__)

#: Strict E.164: plus sign, non-zero country code, 8-15 digits total.
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

DEFAULT_BASE_URL = "https://api.textbee.dev/api/v1"


class TextBeeError(RuntimeError):
    """Base class for TextBee failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable


class TextBeeConfigurationError(TextBeeError):
    """Raised when the gateway is not configured."""


class TextBeeSendError(TextBeeError):
    """Raised when TextBee rejects a message."""


def is_e164_phone(value: str | None) -> bool:
    """Return ``True`` for a strict E.164 number (``+967770447622``)."""
    return bool(E164_RE.fullmatch((value or "").strip()))


def mask_phone(value: str | None) -> str:
    """Return a non-secret rendering of a phone number."""
    digits = (value or "").strip()
    if len(digits) <= 6:
        return "***"
    return f"{digits[:4]}***{digits[-2:]}"


class TextBeeService:
    """Client for the TextBee SMS gateway."""

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
        self._base_url = (
            (self.settings.textbee_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
            or DEFAULT_BASE_URL
        )

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def configuration_status(self) -> dict[str, Any]:
        """Return non-secret readiness for the TextBee channel."""
        missing = self.settings.textbee_missing_settings()
        return {
            "provider": "textbee",
            "valid": not missing,
            "configured": self.settings.textbee_configured,
            "base_url": self._base_url,
            "device_id": self.settings.textbee_device_id or None,
            "missing": missing,
        }

    def _require_configured(self) -> None:
        missing = self.settings.textbee_missing_settings()
        if missing:
            raise TextBeeConfigurationError(
                "TextBee is not configured; set "
                + ", ".join(missing)
                + " in backend/.env"
            )

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": (self.settings.textbee_api_key or "").strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one request and decode the JSON envelope.

        Raises:
            TextBeeSendError: Transport failure, non-JSON body or HTTP error.
        """
        url = f"{self._base_url}{path}"
        timeout = httpx.Timeout(float(self.settings.textbee_timeout_seconds or 20.0))
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, url, json=json_body, params=params, headers=self._headers()
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method,
                        url,
                        json=json_body,
                        params=params,
                        headers=self._headers(),
                    )
        except httpx.TimeoutException as exc:
            raise TextBeeSendError(
                f"TextBee {method} {path} timed out", error_code="timeout", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise TextBeeSendError(
                f"TextBee {method} {path} transport error: {exc}",
                error_code="transport_error",
                retryable=True,
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TextBeeSendError(
                f"TextBee {method} {path} returned a non-JSON response "
                f"(HTTP {response.status_code})",
                status_code=response.status_code,
                error_code="invalid_response",
            ) from exc

        if response.status_code >= 400:
            message = ""
            error_code = None
            if isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("error") or "")
                error_code = payload.get("errorCode") or payload.get("code")
            raise TextBeeSendError(
                message or f"TextBee returned HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=str(error_code) if error_code else None,
                retryable=response.status_code == 429,
            )
        if not isinstance(payload, dict):
            raise TextBeeSendError(
                f"TextBee {method} {path} returned an unexpected payload",
                status_code=response.status_code,
                error_code="invalid_response",
            )
        return payload

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def list_devices(self) -> list[dict[str, Any]]:
        """Return the Android devices registered to the account."""
        self._require_configured()
        payload = await self._request("GET", "/gateway/devices")
        data = payload.get("data")
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    async def resolve_device_id(self) -> str | None:
        """Return the configured device id, or the account's default device.

        The API can send from the default phone without a ``deviceId``, so a
        missing id is not fatal; resolving it keeps the request explicit and
        lets the UI show which phone is used.
        """
        configured = (self.settings.textbee_device_id or "").strip()
        if configured and not configured.lower().startswith(("your", "change_me", "<")):
            return configured
        for device in await self.list_devices():
            if device.get("enabled") and device.get("isDefault"):
                return str(device.get("_id") or "") or None
        for device in await self.list_devices():
            if device.get("enabled"):
                return str(device.get("_id") or "") or None
        return None

    async def verify_configuration(self) -> dict[str, Any]:
        """Validate the key against ``/gateway/stats`` (sends nothing)."""
        status = self.configuration_status()
        if not status["valid"]:
            return {
                **status,
                "valid": False,
                "api_reachable": False,
                "error": "TextBee is not configured; set "
                + ", ".join(status["missing"])
                + " in backend/.env",
            }
        try:
            stats = await self._request("GET", "/gateway/stats")
        except TextBeeError as exc:
            return {
                **status,
                "valid": False,
                "api_reachable": False,
                "error": str(exc),
                "error_code": exc.error_code,
                "status_code": exc.status_code,
            }
        data = stats.get("data") if isinstance(stats.get("data"), dict) else {}
        return {
            **status,
            "api_reachable": True,
            "device_count": data.get("totalDeviceCount"),
            "sent_count": data.get("totalSentSMSCount"),
            "message": "TextBee API key accepted.",
        }

    async def send_sms(self, to_phone: str, message: str) -> dict[str, Any]:
        """Send one SMS through TextBee and describe the outcome.

        Args:
            to_phone: Recipient in E.164 format.
            message: Message body (Unicode is supported; long text is split by
                the carrier into segments).

        Returns:
            ``{"success", "batch_id", "message_id", "device_id", "recipients",
            "error", "error_code", "status_code", "raw"}``.  A configuration or
            provider failure is returned with ``success=False``; this method
            never raises so a campaign batch can continue.
        """
        recipient = (to_phone or "").strip()
        body = (message or "").strip()
        result: dict[str, Any] = {
            "success": False,
            "provider": "textbee",
            "batch_id": None,
            "message_id": None,
            "device_id": (self.settings.textbee_device_id or "").strip() or None,
            "recipients": [recipient] if recipient else [],
            "error": None,
            "error_code": None,
            "status_code": None,
            "raw": None,
        }
        if not is_e164_phone(recipient):
            result["error"] = (
                "recipient phone must be in E.164 format (for example "
                "+967500000000)"
            )
            result["error_code"] = "invalid_recipient"
            return result
        if not body:
            result["error"] = "message cannot be empty"
            result["error_code"] = "empty_message"
            return result
        # GSM-7 holds 160 septets, UCS-2 (Arabic/emoji) only 70.  Reporting the
        # real encoding and segment count keeps cost and delivery accounting
        # honest instead of counting raw characters.
        segments = segment_info(body)
        result.update(
            encoding=segments.encoding,
            segments=segments.segments,
            characters=segments.units,
        )
        try:
            self._require_configured()
            device_id = await self.resolve_device_id()
            payload: dict[str, Any] = {"recipients": [recipient], "message": body}
            if device_id:
                payload["deviceId"] = device_id
            data = await self._request(
                "POST", "/gateway/send-sms", json_body=payload
            )
        except TextBeeError as exc:
            result.update(
                error=str(exc),
                error_code=exc.error_code or "textbee_error",
                status_code=exc.status_code,
            )
            logger.warning(
                "textbee_send_failed",
                to=mask_phone(recipient),
                error_code=exc.error_code,
                status_code=exc.status_code,
            )
            return result

        envelope = data.get("data") if isinstance(data.get("data"), dict) else data
        batch_id = (
            envelope.get("smsBatchId")
            or envelope.get("_id")
            or envelope.get("id")
        )
        result.update(
            success=True,
            batch_id=str(batch_id) if batch_id else None,
            message_id=str(batch_id) if batch_id else None,
            device_id=str(envelope.get("deviceId") or result["device_id"] or "") or None,
            raw=envelope,
        )
        logger.info(
            "textbee_sms_queued",
            to=mask_phone(recipient),
            batch_id=result["batch_id"],
            device_id=result["device_id"],
            characters=segments.units,
            encoding=segments.encoding,
            segments=segments.segments,
        )
        if segments.concatenated:
            logger.warning(
                "textbee_sms_multipart",
                to=mask_phone(recipient),
                batch_id=result["batch_id"],
                encoding=segments.encoding,
                segments=segments.segments,
                characters_per_segment=segments.characters_per_segment,
            )
        return result


__all__ = [
    "E164_RE",
    "TextBeeConfigurationError",
    "TextBeeError",
    "TextBeeSendError",
    "TextBeeService",
    "is_e164_phone",
    "mask_phone",
]
