"""Real SMS and WhatsApp delivery through QuickConnect (quickconnect-ye.com).

QuickConnect provides a unified developer API for sending SMS and WhatsApp
messages in Yemen and internationally.

API contract:
- Endpoint: ``{QUICKCONNECT_API_URL}/messages``
- Authorization: ``Bearer qc_live_...``
- Request JSON: ``{"channel": "sms" | "whatsapp" | "auto" | "both", "to": "<phone>", "body": "<text>"}``
- Response JSON: ``{"ids": ["<msg_id>"], "status": "queued", "balance_yer": ...}``
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Valid phone regex: E.164, local Yemeni 9-digit (70/71/73/77), or leading zero.
PHONE_CLEAN_RE = re.compile(r"[\s\-\(\)]")


class QuickConnectError(RuntimeError):
    """Base exception for QuickConnect failures."""


class QuickConnectConfigurationError(QuickConnectError):
    """Raised when QuickConnect credentials or settings are missing."""


class QuickConnectSendError(QuickConnectError):
    """Raised when QuickConnect rejects a message or transport fails."""


def normalize_phone_number(phone: str | None) -> str:
    """Normalize phone number for QuickConnect dispatch.

    QuickConnect supports:
    - 9-digit Yemeni local numbers: ``771234567``
    - Leading zero: ``0771234567`` -> ``771234567``
    - International E.164: ``+967771234567``, ``+966500000000``
    """
    if not phone:
        return ""
    clean = PHONE_CLEAN_RE.sub("", phone.strip())
    # If starting with 00, replace with +
    if clean.startswith("00"):
        clean = "+" + clean[2:]
    return clean


normalize_phone = normalize_phone_number



class QuickConnectService:
    """Send SMS and WhatsApp messages through the QuickConnect API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client

    @property
    def api_url(self) -> str:
        url = (self.settings.quickconnect_api_url or "").strip().rstrip("/")
        if not url:
            url = "https://aalcgjgocszngpcqzjih.supabase.co/functions/v1/public-api"
        return url

    @property
    def api_key(self) -> str:
        return (self.settings.quickconnect_api_key or "").strip()

    @property
    def is_configured(self) -> bool:
        """Return True if QuickConnect is configured with an API key."""
        return self.settings.quickconnect_configured

    def configuration_status(self, channel: str = "sms") -> dict[str, Any]:
        """Return non-secret configuration readiness for QuickConnect."""
        valid = self.settings.quickconnect_configured
        missing = [] if valid else ["QUICKCONNECT_API_KEY"]
        return {
            "valid": valid,
            "configured": valid,
            "provider": "quickconnect",
            "channel": channel,
            "from": "QuickConnect Gateway",
            "missing": missing,
            "api_url": self.api_url,
        }

    async def get_balance(self) -> dict[str, Any]:
        """Fetch current balance from QuickConnect.

        Returns:
            ``{"balance_yer": int}``
        """
        if not self.api_key:
            raise QuickConnectConfigurationError("QUICKCONNECT_API_KEY is not configured")

        url = f"{self.api_url}/balance"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        timeout = float(self.settings.quickconnect_timeout_seconds or 15.0)

        try:
            if self._http_client:
                response = await self._http_client.get(url, headers=headers, timeout=timeout)
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, headers=headers)
        except Exception as exc:
            raise QuickConnectSendError(f"Connection to QuickConnect failed: {exc}") from exc

        if response.status_code == 401:
            raise QuickConnectConfigurationError("Invalid QuickConnect API key (HTTP 401)")
        if not response.is_success:
            raise QuickConnectSendError(
                f"QuickConnect balance check failed with HTTP {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except Exception as exc:
            raise QuickConnectSendError(f"QuickConnect returned invalid JSON: {response.text}") from exc

    async def send_message(
        self,
        to_phone: str,
        text: str,
        channel: str = "sms",
    ) -> str:
        """Send an SMS or WhatsApp message via QuickConnect.

        Args:
            to_phone: Recipient phone number.
            text: Message body (supports Arabic text).
            channel: ``sms`` or ``whatsapp``.

        Returns:
            The message id returned by QuickConnect.
        """
        if not self.settings.quickconnect_configured:
            raise QuickConnectConfigurationError(
                "QuickConnect delivery is not configured; set QUICKCONNECT_API_KEY in backend/.env"
            )

        recipient = normalize_phone_number(to_phone)
        if not recipient:
            raise QuickConnectSendError("Recipient phone number cannot be empty")

        body = (text or "").strip()
        if not body:
            raise QuickConnectSendError(f"{channel.upper()} text cannot be empty")

        req_channel = "whatsapp" if channel.lower() == "whatsapp" else "sms"
        payload = {
            "channel": req_channel,
            "to": recipient,
            "body": body,
        }
        url = f"{self.api_url}/messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = float(self.settings.quickconnect_timeout_seconds or 15.0)

        logger.info(
            "quickconnect_send_attempt",
            channel=req_channel,
            to=recipient,
            length=len(body),
        )

        try:
            if self._http_client:
                response = await self._http_client.post(url, json=payload, headers=headers, timeout=timeout)
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except Exception as exc:
            raise QuickConnectSendError(f"QuickConnect request failed: {exc}") from exc

        if response.status_code == 401:
            raise QuickConnectConfigurationError("QuickConnect rejected API key (HTTP 401)")
        if response.status_code == 402:
            raise QuickConnectSendError("QuickConnect insufficient balance (HTTP 402)")
        if response.status_code == 400:
            raise QuickConnectSendError(f"QuickConnect bad request: {response.text}")

        if not response.is_success:
            raise QuickConnectSendError(
                f"QuickConnect returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise QuickConnectSendError(f"QuickConnect response was not valid JSON: {response.text}") from exc

        # Extract message ID: {"ids": ["msg_id_1"], ...}
        ids = data.get("ids") or []
        if isinstance(ids, list) and ids:
            message_id = str(ids[0])
        elif data.get("id"):
            message_id = str(data["id"])
        elif data.get("message_id"):
            message_id = str(data["message_id"])
        else:
            message_id = f"qc_{recipient}_{req_channel}"

        logger.info(
            "quickconnect_send_success",
            channel=req_channel,
            to=recipient,
            message_id=message_id,
            balance=data.get("balance_yer"),
        )
        return message_id

    async def send_sms(self, to_phone: str, text: str) -> str:
        """Send an SMS message and return the provider message ID."""
        return await self.send_message(to_phone=to_phone, text=text, channel="sms")

    async def send_whatsapp(self, to_phone: str, text: str) -> str:
        """Send a WhatsApp message and return the provider message ID."""
        return await self.send_message(to_phone=to_phone, text=text, channel="whatsapp")
