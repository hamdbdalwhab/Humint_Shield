"""Organization branding endpoints.

The branding tab owns the company name, primary colour, support address and
logo used by the visual email editor.  The logo is stored as a normalised PNG in
the database and served from an unauthenticated, cacheable public endpoint so
email clients can load it without a session.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import Organization, User
from app.schemas.organization import BrandingPublic, BrandingUpdate
from app.services.email_design import logo_url_for_organization

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/branding",
    tags=["branding"],
    dependencies=[Depends(rate_limit(scope="branding"))],
)
public_router = APIRouter(prefix="/public/branding", tags=["branding"])

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_DIMENSION = 1600


def _branding_public(organization: Organization) -> BrandingPublic:
    """Serialise an organization's branding for the browser.

    Args:
        organization: Organization row.

    Returns:
        Public branding payload with an absolute logo URL.
    """
    settings = get_settings()
    return BrandingPublic(
        organization_id=organization.id,
        company_name=organization.name,
        primary_color=organization.brand_primary_color or "#0F6CBD",
        support_email=organization.brand_support_email,
        logo_url=logo_url_for_organization(organization, settings.base_url),
        has_logo=bool(organization.brand_logo_data),
        updated_at=organization.updated_at,
    )


@router.get("", response_model=BrandingPublic, summary="Get organization branding")
async def get_branding(
    org_id: uuid.UUID,
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> BrandingPublic:
    """Return the branding currently applied to new templates."""
    return _branding_public(organization)


@router.put("", response_model=BrandingPublic, summary="Update organization branding")
async def update_branding(
    org_id: uuid.UUID,
    payload: BrandingUpdate,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> BrandingPublic:
    """Update the company name, primary colour and support address."""
    if payload.company_name is not None:
        organization.name = payload.company_name.strip()
    if payload.primary_color is not None:
        organization.brand_primary_color = payload.primary_color
    if "support_email" in payload.model_fields_set:
        organization.brand_support_email = (
            str(payload.support_email) if payload.support_email else None
        )
    await db.commit()
    await db.refresh(organization)
    logger.info("branding_updated", org_id=str(org_id), user_id=str(user.id))
    return _branding_public(organization)


@router.post("/logo", response_model=BrandingPublic, summary="Upload a company logo")
async def upload_logo(
    org_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> BrandingPublic:
    """Validate, normalise and store a company logo.

    Only raster images are accepted.  Re-encoding through Pillow strips EXIF and
    any embedded active payload; SVG is rejected because it can contain script.
    """
    raw = await file.read(MAX_LOGO_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="The uploaded logo is empty")
    if len(raw) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo must be 2 MB or smaller",
        )
    try:
        Image.MAX_IMAGE_PIXELS = 20_000_000
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=400, detail="Logo must be a PNG, JPEG, GIF or WebP image"
        ) from exc

    if image.width > MAX_LOGO_DIMENSION or image.height > MAX_LOGO_DIMENSION:
        image.thumbnail((MAX_LOGO_DIMENSION, MAX_LOGO_DIMENSION), Image.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)

    organization.brand_logo_data = buffer.getvalue()
    organization.brand_logo_mime = "image/png"
    organization.brand_logo_updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(organization)
    logger.info("branding_logo_uploaded", org_id=str(org_id), user_id=str(user.id))
    return _branding_public(organization)


@router.delete("/logo", response_model=BrandingPublic, summary="Remove the company logo")
async def delete_logo(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> BrandingPublic:
    """Remove the stored logo and fall back to the branded initial mark."""
    organization.brand_logo_data = None
    organization.brand_logo_mime = None
    organization.brand_logo_updated_at = None
    await db.commit()
    await db.refresh(organization)
    logger.info("branding_logo_deleted", org_id=str(org_id), user_id=str(user.id))
    return _branding_public(organization)


@public_router.get("/{org_id}/logo", summary="Serve an organization logo for email clients")
async def public_logo(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return the stored logo without authentication.

    The UUID is unguessable and the response is cacheable; email clients cannot
    send an Authorization header.
    """
    organization = await db.get(Organization, org_id)
    if organization is None or not organization.brand_logo_data:
        raise HTTPException(status_code=404, detail="Logo not found")
    return Response(
        content=organization.brand_logo_data,
        media_type=organization.brand_logo_mime or "image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


__all__ = ["public_router", "router"]
