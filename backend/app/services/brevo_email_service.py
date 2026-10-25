"""Brevo (Sendinblue) transactional email service.

Wraps the official ``sib-api-v3-sdk`` with:

* retry + exponential backoff (2s, 4s, 8s) on transient failures,
* a hard timeout (the SDK call runs in a worker thread),
* structured logging with a correlation id for every attempt,
* an optional ``EMAIL_DRY_RUN`` mode so development environments do not
  dispatch real mail.
"""
from __future__ import annotations

import asyncio
import re
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import unescape
from typing import Any

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.services.retry import RetryExhausted, retry_async

logger = get_logger(__name__)

#: Where an administrator authorises (or removes the restriction on) this host.
AUTHORISED_IPS_URL = "https://app.brevo.com/security/authorised_ips"

#: Brevo reports the blocked egress address inside the error body.  The
#: trailing separator (sentence period, comma, space) must not be captured.
_BLOCKED_IP_RE = re.compile(r"unrecognised IP address\s+([0-9a-fA-F:]+(?:\.[0-9a-fA-F:]+)*)")


def _describe_failure(message: str) -> dict[str, Any]:
    """Turn a raw Brevo error into an actionable instruction.

    Args:
        message: The exception text returned by the SDK.

    Returns:
        ``{}`` when the failure is not recognised, otherwise a mapping with
        ``action_required``, ``hint`` and, for the IP allowlist case,
        ``blocked_ip``/``action_url``.
    """
    match = _BLOCKED_IP_RE.search(message)
    if match:
        blocked_ip = match.group(1)
        return {
            "action_required": "ip_allowlist",
            "blocked_ip": blocked_ip,
            "action_url": AUTHORISED_IPS_URL,
            "hint": (
                "Your server IP is blocked by the email provider. Please allowlist it "
                "in your Brevo dashboard. "
                f"Brevo reports the public IP as {blocked_ip}. Open Brevo → Security → "
                "Authorised IPs, add that address, or deactivate the IP restriction. "
                "Nothing else is blocking delivery."
            ),
        }
    lowered = message.lower()
    if "unauthorized" in lowered or "401" in lowered:
        return {
            "action_required": "credentials",
            "action_url": "https://app.brevo.com/settings/keys/api",
            "hint": "Brevo rejected the API key. Regenerate it and update BREVO_API_KEY.",
        }
    if any(token in lowered for token in ("authentication", "535", "534", "username and password")):
        return {
            "action_required": "smtp_credentials",
            "hint": (
                "The SMTP server rejected the username/password. For Gmail, create a "
                "16-character App Password (Google Account → Security → 2-Step "
                "Verification → App passwords) and set SMTP_PASSWORD to it."
            ),
        }
    return {}


@dataclass(slots=True)
class SendResult:
    """Outcome of a single send attempt.

    Attributes:
        success: Whether the message was accepted by Brevo.
        message_id: Brevo message id when successful.
        error: Human readable error message when not successful.
    """

    success: bool
    message_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {"success": self.success, "message_id": self.message_id, "error": self.error}


class BrevoNotConfiguredError(RuntimeError):
    """Raised when no usable Brevo API key is configured."""


class BrevoEmailService:
    """Async facade over the synchronous Brevo SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Load configuration.

        Args:
            settings: Optional settings override (used by tests).
        """
        self.settings = settings or get_settings()
        self.api_key = self.settings.brevo_api_key
        self.from_email = self.settings.from_email
        self.from_name = self.settings.from_name
        self.dry_run = self.settings.email_dry_run
        self.max_retries = max(1, self.settings.email_max_retries)
        self.timeout = self.settings.email_timeout_seconds
        self.retry_base_delay = self.settings.email_retry_base_delay
        self.use_smtp = self.settings.smtp_transport

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _html_to_text(html_content: str) -> str:
        """Build a readable plain-text alternative for the HTML body.

        Multipart messages score better with spam filters and remain legible in
        clients that block remote images.
        """
        text = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            " ",
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return text.strip()

    # ------------------------------------------------------------------ #
    # SDK plumbing
    # ------------------------------------------------------------------ #
    def _build_api(self):
        """Instantiate the Brevo ``TransactionalEmailsApi`` client.

        Returns:
            A configured ``TransactionalEmailsApi`` instance.

        Raises:
            BrevoNotConfiguredError: When the API key is missing/placeholder.
            RuntimeError: When the SDK is not installed.
        """
        if not self.settings.brevo_configured:
            raise BrevoNotConfiguredError(
                "BREVO_API_KEY is not configured (set it in the environment)"
            )
        try:
            import sib_api_v3_sdk
            from sib_api_v3_sdk.rest import ApiException  # noqa: F401
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("sib-api-v3-sdk is not installed") from exc

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = self.api_key
        client = sib_api_v3_sdk.ApiClient(configuration)
        return sib_api_v3_sdk.TransactionalEmailsApi(client)

    def _build_account_api(self):
        """Instantiate the Brevo ``AccountApi`` client used by the self-check.

        Kept separate from :meth:`_build_api` so the diagnostic can be stubbed
        in tests without ever reaching the network.

        Returns:
            A configured ``AccountApi`` instance.

        Raises:
            BrevoNotConfiguredError: When the API key is missing/placeholder.
            RuntimeError: When the SDK is not installed.
        """
        if not self.settings.brevo_configured:
            raise BrevoNotConfiguredError(
                "BREVO_API_KEY is not configured (set it in the environment)"
            )
        try:
            import sib_api_v3_sdk
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("sib-api-v3-sdk is not installed") from exc

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = self.api_key
        client = sib_api_v3_sdk.ApiClient(configuration)
        return sib_api_v3_sdk.AccountApi(client)

    def _send_sync(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        correlation_id: str,
    ) -> SendResult:
        """Perform the blocking SDK call (executed in a worker thread).

        Args:
            to_email: Recipient address.
            to_name: Recipient display name.
            subject: Rendered subject line.
            html_content: Rendered HTML body.
            correlation_id: Correlation id for logging.

        Returns:
            A :class:`SendResult`.
        """
        if self.dry_run:
            logger.info(
                "email_dry_run",
                to=to_email,
                subject=subject,
                transport="smtp" if self.use_smtp else "brevo",
                correlation_id=correlation_id,
            )
            return SendResult(success=True, message_id=f"dry-run-{uuid.uuid4()}")

        if self.use_smtp:
            return self._send_smtp_sync(
                to_email, to_name, subject, html_content, correlation_id
            )

        try:
            from sib_api_v3_sdk.rest import ApiException

            api = self._build_api()
            import sib_api_v3_sdk

            payload = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to_email, "name": to_name or to_email}],
                sender={"email": self.from_email, "name": self.from_name},
                reply_to={"email": self.from_email, "name": self.from_name},
                subject=subject,
                html_content=html_content,
                text_content=self._html_to_text(html_content),
            )
            response = api.send_transac_email(payload)
            message_id = getattr(response, "message_id", None) or getattr(
                response, "messageId", None
            )
            logger.info(
                "brevo_send_ok",
                to=to_email,
                message_id=message_id,
                correlation_id=correlation_id,
            )
            return SendResult(success=True, message_id=str(message_id) if message_id else None)
        except BrevoNotConfiguredError as exc:
            return SendResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - normalise every SDK error
            # ``ApiException`` carries the HTTP status and body; surface both.
            status = getattr(exc, "status", None)
            body = getattr(exc, "body", None)
            detail = str(body) if body else str(exc)
            logger.warning(
                "brevo_send_failed",
                to=to_email,
                status=status,
                error=detail,
                correlation_id=correlation_id,
            )
            raise BrevoTransientError(detail, status=status) from exc

    # ------------------------------------------------------------------ #
    # SMTP transport (Gmail / Brevo relay / any authenticated mailbox)
    # ------------------------------------------------------------------ #
    def _open_smtp(self) -> smtplib.SMTP:
        """Open an authenticated SMTP connection.

        Returns:
            A connected and authenticated ``SMTP``/``SMTP_SSL`` client.

        Raises:
            RuntimeError: When SMTP settings are incomplete.
            smtplib.SMTPException: When the server rejects the connection/login.
        """
        if not self.settings.smtp_configured:
            raise RuntimeError(
                "SMTP is selected but SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD are not set"
            )
        host = self.settings.smtp_host
        port = self.settings.smtp_port
        if self.settings.smtp_use_ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=self.timeout)
        else:
            client = smtplib.SMTP(host, port, timeout=self.timeout)
            client.ehlo()
            client.starttls()
            client.ehlo()
        client.login(self.settings.smtp_username, self.settings.smtp_password)
        return client

    def _send_smtp_sync(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        correlation_id: str,
    ) -> SendResult:
        """Send one message through SMTP (executed in a worker thread).

        The envelope sender equals the authenticated mailbox, so Gmail's
        SPF/DKIM/DMARC checks pass and simulations land in the inbox instead
        of Spam.
        """
        try:
            message = EmailMessage()
            message["From"] = formataddr((self.from_name, self.from_email))
            message["To"] = formataddr((to_name or to_email, to_email))
            message["Subject"] = subject
            message_id = make_msgid(domain=self.from_email.split("@")[-1] or None)
            message["Message-ID"] = message_id
            plain = self._html_to_text(html_content)
            message.set_content(plain or "Please view this email in an HTML-capable client.")
            message.add_alternative(html_content, subtype="html")

            with self._open_smtp() as client:
                client.send_message(message)

            logger.info(
                "smtp_send_ok",
                to=to_email,
                message_id=message_id,
                host=self.settings.smtp_host,
                correlation_id=correlation_id,
            )
            return SendResult(success=True, message_id=message_id)
        except RuntimeError as exc:
            logger.warning("smtp_not_configured", error=str(exc), correlation_id=correlation_id)
            return SendResult(success=False, error=str(exc))
        except smtplib.SMTPAuthenticationError as exc:
            detail = f"SMTP authentication failed: {exc}"
            logger.warning("smtp_auth_failed", error=detail, correlation_id=correlation_id)
            raise BrevoTransientError(detail, status=401) from exc
        except (smtplib.SMTPException, OSError) as exc:
            detail = f"SMTP delivery failed: {exc}"
            logger.warning("smtp_send_failed", error=detail, correlation_id=correlation_id)
            raise BrevoTransientError(detail) from exc

    async def send_training_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        html_content: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a training email with retry on transient failures.

        Args:
            to_email: Recipient address.
            to_name: Recipient display name.
            subject: Subject line.
            html_content: HTML body.
            correlation_id: Optional correlation id (generated if omitted).

        Returns:
            ``{"success": bool, "message_id": str | None, "error": str | None}``.
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        attempts = self.max_retries

        async def _attempt() -> SendResult:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._send_sync, to_email, to_name, subject, html_content, correlation_id
                ),
                timeout=self.timeout,
            )

        try:
            result = await retry_async(
                _attempt,
                attempts=attempts,
                base_delay=self.retry_base_delay,
                backoff_factor=2.0,
                # A 4xx is a permanent rejection (bad recipient, unverified sender,
                # revoked key): retrying only burns the backoff budget.
                should_retry=lambda exc: not getattr(exc, "is_permanent", False),
                operation_name="brevo.send_training_email",
                correlation_id=correlation_id,
            )
            return result.as_dict()
        except RetryExhausted as exc:
            if exc.permanent:
                # Brevo rejected the message outright (4xx): say so rather than
                # implying the retry budget was used up.
                return SendResult(
                    success=False, error=f"brevo rejected the message: {exc.last_error}"
                ).as_dict()
            return SendResult(
                success=False, error=f"retry exhausted: {exc.last_error}"
            ).as_dict()
        except TimeoutError:
            logger.error("brevo_timeout", to=to_email, correlation_id=correlation_id)
            return SendResult(success=False, error="request timed out").as_dict()
        except Exception as exc:  # noqa: BLE001 - never raise to the caller
            logger.error(
                "brevo_unexpected_error",
                to=to_email,
                error=str(exc),
                correlation_id=correlation_id,
            )
            return SendResult(success=False, error=str(exc)).as_dict()

    async def verify_configuration(self) -> dict[str, Any]:
        """Validate the Brevo key by calling the account endpoint.

        Returns:
            ``{"valid", "error", "detail"}`` plus, when Brevo rejects the
            request, an actionable ``action_required``/``action_url``/``hint``.
        """
        if self.dry_run:
            return {
                "valid": True,
                "error": None,
                "detail": {
                    "mode": "dry-run",
                    "transport": "smtp" if self.use_smtp else "brevo",
                    "from_email": self.from_email,
                },
            }

        if self.use_smtp:
            if not self.settings.smtp_configured:
                return {
                    "valid": False,
                    "error": "SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD are not configured",
                    "detail": None,
                }

            def _check_smtp() -> dict[str, Any]:
                with self._open_smtp() as client:
                    client.noop()
                return {
                    "transport": "smtp",
                    "host": self.settings.smtp_host,
                    "port": self.settings.smtp_port,
                    "from_email": self.from_email,
                }

            try:
                detail = await asyncio.wait_for(
                    asyncio.to_thread(_check_smtp), timeout=self.timeout
                )
                return {"valid": True, "error": None, "detail": detail}
            except Exception as exc:  # noqa: BLE001
                logger.warning("smtp_verify_failed", error=str(exc))
                return {
                    "valid": False,
                    "error": str(exc),
                    "detail": None,
                    **_describe_failure(str(exc)),
                }

        if not self.settings.brevo_configured:
            return {"valid": False, "error": "BREVO_API_KEY is not configured", "detail": None}

        def _check() -> dict[str, Any]:
            account_api = self._build_account_api()
            account = account_api.get_account()
            return {
                "email": getattr(account, "email", None),
                "company_name": getattr(account, "company_name", None),
                "plan": (
                    getattr(getattr(account, "plan", None), "type", None)
                    if getattr(account, "plan", None)
                    else None
                ),
            }

        try:
            detail = await asyncio.wait_for(asyncio.to_thread(_check), timeout=self.timeout)
            return {"valid": True, "error": None, "detail": detail}
        except BrevoNotConfiguredError as exc:
            return {"valid": False, "error": str(exc), "detail": None}
        except Exception as exc:  # noqa: BLE001
            logger.warning("brevo_verify_failed", error=str(exc))
            return {"valid": False, "error": str(exc), "detail": None, **_describe_failure(str(exc))}

    async def send_test_email(self, to_email: str) -> dict[str, Any]:
        """Send a simple diagnostic email.

        Args:
            to_email: Destination address.

        Returns:
            The result of :meth:`send_training_email`.
        """
        html = (
            "<html><body style='font-family:Arial,sans-serif'>"
            "<h2>HUMINT Shield &mdash; email delivery test</h2>"
            "<p>This is a <strong>delivery test</strong>, not a simulation. "
            "If you received it, your Brevo configuration is working.</p>"
            f"<p>Sender: {self.from_email} ({self.from_name})</p>"
            f"<p>Base URL: {self.settings.base_url}</p>"
            "</body></html>"
        )
        return await self.send_training_email(
            to_email=to_email,
            to_name="Test Recipient",
            subject="HUMINT Shield — email delivery test",
            html_content=html,
        )


class BrevoTransientError(RuntimeError):
    """Marks an SDK failure as eligible for retry."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def is_permanent(self) -> bool:
        """Return ``True`` for errors that should not be retried (4xx)."""
        return self.status is not None and 400 <= self.status < 500
