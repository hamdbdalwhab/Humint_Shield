"""Real SMS and WhatsApp delivery through Vonage.

The service wraps the official Vonage Python SDK and returns the provider
message identifier that the delivery/read webhooks use to correlate receipts
with the local ``tracking_events`` row.

Both public send methods are asynchronous: the Vonage SDK is synchronous, so
the blocking HTTP call is executed in a worker thread to keep the FastAPI event
loop responsive.

Notes
-----
* SMS uses the legacy SMS API because it supports ``type="unicode"``, which is
  mandatory for Arabic content.
* WhatsApp uses the Messages API with ``message_type="text"``.
* Phone numbers are stored locally in E.164 form (``+9665...``); Vonage's SMS
  API and Messages API expect the international number without the leading
  ``+``, so it is removed at the boundary only.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Strict E.164: plus sign, non-zero country code, 8-15 digits total.
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class VonageError(RuntimeError):
    """Base class for Vonage delivery failures."""


class VonageConfigurationError(VonageError):
    """Raised when the selected channel is not fully configured."""


class VonageSendError(VonageError):
    """Raised when Vonage rejects a message or the transport fails."""


def is_e164_phone(value: str | None) -> bool:
    """Return ``True`` when ``value`` is a valid E.164 phone number."""
    return bool(value and E164_RE.fullmatch(value.strip()))


def _vonage_number(phone: str) -> str:
    """Convert an E.164 number to the format Vonage expects."""
    return phone.strip().lstrip("+")


class VonageService:
    """Send SMS and WhatsApp messages through the Vonage APIs."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        sms_client: Any | None = None,
        messages_client: Any | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            settings: Optional settings override (tests).
            sms_client: Optional pre-built ``vonage.Sms`` double (tests).
            messages_client: Optional pre-built ``vonage.Messages`` double
                (tests).
        """
        self.settings = settings or get_settings()
        self._sms_client = sms_client
        self._messages_client = messages_client

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def configuration_status(self, channel: str) -> dict[str, Any]:
        """Return non-secret configuration readiness for ``channel``.

        Args:
            channel: ``sms`` or ``whatsapp``.

        Returns:
            A dictionary with ``valid``, ``missing`` and the configured sender
            where applicable.  No secrets are returned.
        """
        missing = self.settings.vonage_missing_settings(channel)
        if channel == "sms":
            valid = self.settings.vonage_sms_configured
            sender = self.settings.vonage_sms_from
        elif channel == "whatsapp":
            valid = self.settings.vonage_whatsapp_configured
            sender = self.settings.vonage_whatsapp_from
        else:
            raise ValueError(f"unsupported Vonage channel: {channel!r}")
        return {
            "valid": valid,
            "configured": self.settings.vonage_configured,
            "channel": channel,
            "from": sender,
            "missing": missing,
            "application_configured": self.settings.vonage_application_configured,
            "messages_base_url": (
                self.settings.vonage_messages_base_url or "https://api.nexmo.com"
            ),
        }

    async def send_sms(self, to_phone: str, text: str) -> str:
        """Send a Unicode SMS and return the Vonage message id.

        Args:
            to_phone: Recipient in E.164 format.
            text: Message body (Arabic is supported through ``type=unicode``).

        Returns:
            The provider ``message-id`` used for DLR correlation.

        Raises:
            VonageConfigurationError: When credentials/sender are missing.
            VonageSendError: When the recipient, payload or provider fails.
        """
        self._require_channel("sms")
        to_phone = self._validate_recipient(to_phone)
        body = (text or "").strip()
        if not body:
            raise VonageSendError("SMS text cannot be empty")

        payload = {
            "from": (self.settings.vonage_sms_from or "").strip(),
            "to": _vonage_number(to_phone),
            "text": body,
            "type": "unicode",
            # Ask Vonage for a per-message DLR and tell it where to post it.
            # The account-level callback can also be configured in the dashboard.
            "status-report-req": 1,
            "callback": self._sms_callback_url(),
        }
        client = self._sms_client or self._build_sms_client()

        try:
            response = await asyncio.to_thread(client.send_message, payload)
        except Exception as exc:  # noqa: BLE001 - transport/provider errors are data
            raise VonageSendError(f"Vonage SMS request failed: {exc}") from exc

        message = self._first_sms_message(response)
        status = str(message.get("status", "")).strip()
        if status != "0":
            detail = (
                message.get("error-text")
                or message.get("error_text")
                or message.get("error")
                or f"status {status or 'unknown'}"
            )
            raise VonageSendError(f"Vonage SMS rejected the message: {detail}")

        message_id = message.get("message-id") or message.get("message_id")
        if not message_id:
            raise VonageSendError("Vonage SMS response did not contain a message-id")
        logger.info(
            "vonage_sms_accepted",
            message_id=str(message_id),
            to=_mask_phone(to_phone),
        )
        return str(message_id)

    async def send_whatsapp(self, to_phone: str, text: str) -> str:
        """Send a WhatsApp text message and return the Vonage message UUID.

        Args:
            to_phone: Recipient in E.164 format.
            text: Message body (Arabic is supported by the Messages API).

        Returns:
            The provider ``message_uuid`` used for status/webhook correlation.

        Raises:
            VonageConfigurationError: When credentials/sender are missing.
            VonageSendError: When the recipient, payload or provider fails.
        """
        self._require_channel("whatsapp")
        to_phone = self._validate_recipient(to_phone)
        body = (text or "").strip()
        if not body:
            raise VonageSendError("WhatsApp text cannot be empty")

        payload = {
            "channel": "whatsapp",
            "message_type": "text",
            "to": _vonage_number(to_phone),
            "from": _vonage_number((self.settings.vonage_whatsapp_from or "").strip()),
            "text": body,
        }
        client = self._messages_client or self._build_messages_client()

        try:
            # vonage 3.x exposes send_message; newer major versions expose send.
            # Supporting both keeps the service usable after an SDK upgrade.
            sender = getattr(client, "send", None) or getattr(client, "send_message", None)
            if sender is None:  # pragma: no cover - defensive SDK guard
                raise VonageSendError(
                    "Installed Vonage SDK exposes neither Messages.send nor send_message"
                )
            response = await asyncio.to_thread(sender, payload)
        except VonageError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport/provider errors are data
            raise VonageSendError(f"Vonage WhatsApp request failed: {exc}") from exc

        if not isinstance(response, dict):
            raise VonageSendError("Vonage WhatsApp response was not a JSON object")
        message_uuid = (
            response.get("message_uuid")
            or response.get("message_id")
            or response.get("id")
        )
        if not message_uuid:
            detail = response.get("detail") or response.get("title") or response
            raise VonageSendError(
                f"Vonage WhatsApp response did not contain a message_uuid: {detail}"
            )
        logger.info(
            "vonage_whatsapp_accepted",
            message_id=str(message_uuid),
            to=_mask_phone(to_phone),
        )
        return str(message_uuid)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _require_channel(self, channel: str) -> None:
        """Raise a configuration error when ``channel`` is not ready."""
        status = self.configuration_status(channel)
        if status["valid"]:
            return
        missing = ", ".join(status["missing"]) or "sender configuration"
        raise VonageConfigurationError(
            f"Vonage {channel} is not configured; set {missing} in the environment"
        )

    @staticmethod
    def _validate_recipient(to_phone: str) -> str:
        """Assert that a recipient is E.164 and return it normalised."""
        phone = (to_phone or "").strip()
        if not is_e164_phone(phone):
            raise VonageSendError(
                "recipient phone must be in E.164 format (for example +966500000000)"
            )
        return phone

    def _sms_callback_url(self) -> str:
        """Build the DLR callback URL, including the optional shared token."""
        base_url = (self.settings.base_url or "").rstrip("/")
        callback = f"{base_url}/api/v1/webhooks/vonage/dlr"
        token = (self.settings.vonage_webhook_token or "").strip()
        return f"{callback}?token={quote(token)}" if token else callback

    def _build_client(self, *, application_auth: bool = False):
        """Build a shared Vonage SDK client from settings.

        SMS always uses API key/secret authentication.  WhatsApp can use either
        API key/secret or, when an application ID and private key are present,
        JWT authentication.  JWT is required by some Vonage applications and is
        the recommended setup for application-level status webhooks.
        """
        try:
            import vonage
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise VonageConfigurationError(
                "the 'vonage' package is not installed; run pip install -r requirements.txt"
            ) from exc

        kwargs: dict[str, Any] = {
            "key": self.settings.vonage_api_key.strip(),
            "secret": self.settings.vonage_api_secret.strip(),
            "timeout": self.settings.vonage_timeout_seconds,
        }
        if application_auth:
            app_id = (self.settings.vonage_application_id or "").strip()
            raw_private_key = (self.settings.vonage_private_key or "").strip()
            if bool(app_id) != bool(raw_private_key):
                raise VonageConfigurationError(
                    "set both VONAGE_APPLICATION_ID and VONAGE_PRIVATE_KEY, or neither"
                )
            if app_id and raw_private_key:
                kwargs["application_id"] = app_id
                kwargs["private_key"] = self._read_private_key(raw_private_key)

        return vonage.Client(**kwargs)

    @staticmethod
    def _read_private_key(raw: str) -> str:
        """Return PEM content from a path or from an inline escaped value."""
        if "BEGIN" in raw:
            return raw.replace("\\n", "\n")
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
        raise VonageConfigurationError(
            "VONAGE_PRIVATE_KEY must be a readable PEM file path or PEM content"
        )

    def _build_sms_client(self):
        """Build the SMS API client (legacy Unicode-capable API)."""
        import vonage

        return vonage.Sms(self._build_client())

    def _build_messages_client(self):
        """Build the Messages API client (WhatsApp)."""
        import vonage

        client = self._build_client(application_auth=True)
        messages_host = (self.settings.vonage_messages_base_url or "").strip()
        if messages_host:
            client.api_host(messages_host.rstrip("/"))
        return vonage.Messages(client)

    @staticmethod
    def _first_sms_message(response: Any) -> dict[str, Any]:
        """Extract the first message object from an SMS API response."""
        if not isinstance(response, dict):
            raise VonageSendError("Vonage SMS response was not a JSON object")
        messages = response.get("messages")
        if not isinstance(messages, list) or not messages:
            detail = (
                response.get("error-text")
                or response.get("error")
                or response.get("detail")
                or response
            )
            raise VonageSendError(f"Vonage SMS response contained no messages: {detail}")
        first = messages[0]
        if not isinstance(first, dict):
            raise VonageSendError("Vonage SMS response message was not an object")
        return first


def _mask_phone(phone: str) -> str:
    """Mask a phone number for logs while retaining the country prefix."""
    digits = (phone or "").lstrip("+")
    if len(digits) <= 6:
        return "***"
    return f"+{digits[:4]}***{digits[-2:]}"


__all__ = [
    "E164_RE",
    "VonageConfigurationError",
    "VonageError",
    "VonageSendError",
    "VonageService",
    "is_e164_phone",
]
