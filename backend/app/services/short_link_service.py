"""Short-link generation for SMS (and other) simulation messages.

The stored link is a stable 6-character code per tracking row.  The public base
comes from ``SHORT_LINK_BASE_URL`` (a clean brand domain such as
``https://hument.link``); when it is not configured the application's own
``BASE_URL`` is used so local development still resolves.

Messages therefore contain ``{short_origin}/s/{code}`` instead of the long
``/api/v1/track/sms/{uuid}`` path.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.models import EmailTracking, ShortLink

logger = get_logger(__name__)

_ALPHABET = string.ascii_letters + string.digits
#: Keyless shortener used when no custom short domain is configured.
VGD_ENDPOINT = "https://v.gd/create.php"


class ShortLinkService:
    """Create and resolve per-recipient simulation short links."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialise the service.

        Args:
            settings: Optional settings override (tests).
        """
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def origin(self) -> str:
        """Return the public origin used in messages (no trailing slash)."""
        configured = (self.settings.short_link_base_url or "").strip()
        return (configured or self.settings.base_url).rstrip("/")

    def public_url(self, code: str) -> str:
        """Return the on-domain URL for ``code`` (custom short domain or base)."""
        return f"{self.origin}/s/{code}"

    async def display_url(self, db: AsyncSession, link: ShortLink) -> str:
        """Return the URL to put in the message, caching it on the row.

        Preference order: the custom short domain (``SHORT_LINK_BASE_URL``),
        then a keyless v.gd shortening of the on-domain link, then the
        on-domain link itself if the shortener is disabled or unavailable.
        """
        if link.display_url:
            return link.display_url

        on_domain = self.public_url(link.code)
        url = on_domain
        provider = (self.settings.short_link_provider or "none").strip().lower()
        if not (self.settings.short_link_base_url or "").strip() and provider == "vgd":
            shortened = await self._shorten_with_vgd(on_domain)
            url = shortened or on_domain

        link.display_url = url
        await db.flush()
        return url

    async def _shorten_with_vgd(self, url: str) -> str | None:
        """Return a v.gd short URL for ``url``, or ``None`` on any failure."""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    VGD_ENDPOINT, params={"format": "simple", "url": url}
                )
        except httpx.HTTPError as exc:  # pragma: no cover - network dependent
            logger.warning("short_link_provider_unavailable", error=str(exc))
            return None
        text = (response.text or "").strip()
        if response.status_code != 200 or not text.startswith("https://"):
            logger.warning(
                "short_link_provider_rejected",
                status_code=response.status_code,
                body=text[:120],
            )
            return None
        return text

    @staticmethod
    def generate_code(length: int = 6) -> str:
        """Return a cryptographically random alphanumeric code."""
        return "".join(secrets.choice(_ALPHABET) for _ in range(length))

    async def ensure_link(
        self,
        db: AsyncSession,
        tracking: EmailTracking,
        *,
        landing_page: str | None = None,
    ) -> ShortLink:
        """Return the tracking row's short link, creating it when missing.

        Args:
            db: Active session (the caller commits).
            tracking: Recipient tracking row.
            landing_page: Optional SMS landing-page slug appended to the
                destination as ``?page=…`` so the landing experience always
                matches the resolved scenario.

        Returns:
            The persisted :class:`ShortLink`.
        """
        existing = await db.scalar(
            select(ShortLink).where(ShortLink.tracking_uuid == tracking.tracking_uuid)
        )
        if existing is not None:
            return existing

        channel = (tracking.channel or "email").strip().lower()
        if channel in {"sms", "whatsapp"}:
            target = f"/sms-lure/{tracking.tracking_uuid}"
        elif channel == "qr":
            target = f"/simulation/qr/{tracking.tracking_uuid}"
        elif channel == "vishing":
            target = f"/simulation/vishing/{tracking.tracking_uuid}"
        elif channel == "pretexting":
            target = f"/simulation/ceo/{tracking.tracking_uuid}"
        else:
            target = f"/phish/{tracking.tracking_uuid}"
        if landing_page:
            target = f"{target}?page={landing_page}"

        code = self.generate_code()
        for _ in range(10):
            taken = await db.scalar(select(ShortLink.id).where(ShortLink.code == code))
            if taken is None:
                break
            code = self.generate_code()
        link = ShortLink(
            code=code, tracking_uuid=tracking.tracking_uuid, target_path=target
        )
        db.add(link)
        await db.flush()
        logger.info(
            "short_link_created",
            code=code,
            tracking_uuid=str(tracking.tracking_uuid),
            channel=channel,
        )
        return link

    async def resolve(self, db: AsyncSession, code: str) -> ShortLink | None:
        """Return the short link for ``code`` (``None`` when unknown)."""
        clean = (code or "").strip()
        if not clean or len(clean) > 16:
            return None
        return await db.scalar(select(ShortLink).where(ShortLink.code == clean))

    @staticmethod
    async def register_click(db: AsyncSession, link: ShortLink) -> None:
        """Increment the click counter and stamp the last click time."""
        link.clicks = int(link.clicks or 0) + 1
        link.last_clicked_at = datetime.now(timezone.utc)
        await db.flush()


__all__ = ["ShortLinkService"]
