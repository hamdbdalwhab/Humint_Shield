"""Custom URL shortener endpoint (unauthenticated)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit
from app.logging_config import get_logger
from app.services.tracking_service import TrackingService

logger = get_logger(__name__)

router = APIRouter(
    tags=["shortener"],
    dependencies=[Depends(rate_limit(limit=600, scope="tracking"))],
)

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get(
    "/s/{short_code}",
    summary="Short URL redirect to simulation tracking landing page",
)
async def resolve_short_url(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Resolve a short code, log click engagement accurately, and 302 redirect."""
    service = TrackingService()
    clean_code = (short_code or "").strip()
    if not clean_code or len(clean_code) > 16:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid short link")

    tracking = await service.resolve_short_code(clean_code, db)
    if tracking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short link not found")

    try:
        await service.log_click(
            tracking.tracking_uuid,
            _client_ip(request),
            request.headers.get("user-agent"),
            db,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("short_code_click_failed", short_code=clean_code, error=str(exc))

    settings = get_settings()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    base_url = f"{proto}://{host}" if host else settings.base_url.rstrip("/")

    channel = (tracking.channel or "email").strip().lower()
    if channel == "qr":
        target = f"{base_url}/simulation/qr/{tracking.tracking_uuid}"
    elif channel == "vishing":
        target = f"{base_url}/simulation/vishing/{tracking.tracking_uuid}"
    elif channel == "pretexting":
        target = f"{base_url}/simulation/ceo/{tracking.tracking_uuid}"
    elif channel in {"sms", "whatsapp"}:
        target = f"{base_url}/training/{tracking.tracking_uuid}"
    else:
        target = f"{base_url}/phish/{tracking.tracking_uuid}"

    logger.info("short_url_redirect", short_code=clean_code, target=target)
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND, headers=NO_CACHE_HEADERS)
