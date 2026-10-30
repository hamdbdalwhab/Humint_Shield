"""Quishing poster generation endpoint.

The campaign APIs are organization-scoped for backwards compatibility, but the
quishing deliverable has a dedicated, documented endpoint:

``POST /api/v1/campaigns/{campaign_id}/generate-qr``

It is authenticated and always scopes the campaign to the caller's
organization.  The response is a **single** print-ready A4 poster (one page)
whose QR code contains one generic campaign URL:

``{BASE_URL}/api/v1/track/qr/{campaign_id}``

No employee name, e-mail or per-recipient tracking UUID is ever embedded in the
poster.  The admin prints one copy and hangs it on the wall.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import EmailCampaign, Organization, User
from app.schemas import QRPosterRequest
from app.services.quishing_service import (
    PosterRecipient,
    build_poster_pack,
    normalize_lure_type,
)

logger = get_logger(__name__)
router = APIRouter(
    prefix="/campaigns",
    tags=["quishing"],
    dependencies=[Depends(rate_limit(scope="campaigns"))],
)


def _merge_poster_overrides(
    channel_config: dict | None,
    payload: QRPosterRequest | None,
) -> dict:
    """Return a channel config with optional lure/branding overrides applied."""
    config = dict(channel_config or {})
    qr_config = config.get("qr")
    qr_values = dict(qr_config) if isinstance(qr_config, dict) else {}
    if payload is not None:
        for field in (
            "headline",
            "body",
            "footer",
            "pretext_key",
            "lure_type",
            "company_name",
            "department",
            "month_label",
            "primary_color",
            "accent_color",
            "logo_data_url",
        ):
            value = getattr(payload, field, None)
            if value is not None and str(value).strip():
                qr_values[field] = str(value).strip()
        if "lure_type" in qr_values:
            qr_values["lure_type"] = normalize_lure_type(qr_values["lure_type"])
        qr_values.pop("pretext_key", None)
    if not qr_values.get("lure_type") and qr_values.get("pretext_key"):
        qr_values["lure_type"] = normalize_lure_type(qr_values["pretext_key"])
    if not qr_values.get("lure_type"):
        qr_values["lure_type"] = normalize_lure_type(None)
    config["qr"] = qr_values
    return config


@router.post(
    "/{campaign_id}/generate-qr",
    summary="Generate the single printable quishing poster",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "One A4 poster"},
        400: {"description": "Campaign is not a QR campaign"},
        404: {"description": "Campaign not found"},
    },
)
async def generate_qr_posters(
    campaign_id: uuid.UUID,
    payload: QRPosterRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> Response:
    """Generate one generic campaign poster (no employee names).

    The QR encodes ``/api/v1/track/qr/{campaign_id}``.  A scan is therefore
    anonymous until the visitor submits the credential form, at which point the
    backend resolves the identity from the entered e-mail/username.
    """
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    if (campaign.channel or "").strip().lower() != "qr":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="QR posters can only be generated for a qr campaign",
        )

    organization = await db.get(Organization, campaign.organization_id)
    if organization is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    settings = get_settings()
    base_url = settings.base_url.rstrip("/")
    recipients = [
        PosterRecipient(
            name="",
            email="",
            tracking_uuid="",
            tracking_url=f"{base_url}/api/v1/track/qr/{campaign.id}",
        )
    ]

    campaign.channel_config = _merge_poster_overrides(campaign.channel_config, payload)
    await db.commit()

    try:
        pdf_bytes = build_poster_pack(
            organization=organization,
            campaign=campaign,
            recipients=recipients,
            channel_config=campaign.channel_config,
            support_email=organization.brand_support_email,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - explicit 500, never a corrupt PDF
        logger.error(
            "qr_poster_generation_failed",
            campaign_id=str(campaign.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate the QR poster",
        ) from exc

    logger.info(
        "qr_poster_generated",
        campaign_id=str(campaign.id),
        organization_id=str(campaign.organization_id),
        pages=1,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="campaign-{campaign.id}-poster.pdf"'
            ),
            "Cache-Control": "no-store",
            "X-Poster-Count": "1",
        },
    )


__all__ = ["router"]
