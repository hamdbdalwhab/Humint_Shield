"""Stable Brevo service contract used by the campaign launcher.

The implementation lives in :mod:`app.services.brevo_email_service` because it
also supports an SMTP transport for local mailboxes.  This module exposes the
small, channel-facing API required by the Email Channel:

``await BrevoService().send_email(to_email, subject, html_content)``
    -> ``{"success": bool, "message_id": str | None, "error": str | None}``

Transient failures are retried up to ``EMAIL_MAX_RETRIES`` (default: three
attempts).  Permanent Brevo 4xx responses are not retried.
"""
from __future__ import annotations

from typing import Any

from app.services.brevo_email_service import BrevoEmailService


class BrevoService:
    """Thin facade over the production Brevo/SMTP transport."""

    def __init__(self, transport: BrevoEmailService | None = None) -> None:
        self._transport = transport or BrevoEmailService()

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        *,
        to_name: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one transactional email.

        Args:
            to_email: Recipient address.
            subject: Rendered subject line.
            html_content: Rendered HTML body (already personalised and with
                the tracking pixel / rewritten links).
            to_name: Optional recipient display name.
            correlation_id: Optional correlation id for logs.

        Returns:
            ``{"success", "message_id", "error"}``.
        """
        return await self._transport.send_training_email(
            to_email=to_email,
            to_name=to_name or to_email,
            subject=subject,
            html_content=html_content,
            correlation_id=correlation_id,
        )


async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    to_name: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Module-level convenience wrapper for :meth:`BrevoService.send_email`."""
    return await BrevoService().send_email(
        to_email,
        subject,
        html_content,
        to_name=to_name,
        correlation_id=correlation_id,
    )


__all__ = ["BrevoService", "send_email"]
