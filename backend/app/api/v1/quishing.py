"""Quishing poster generation endpoint.

The campaign APIs are organization-scoped for backwards compatibility, but the
quishing deliverable has a dedicated, documented endpoint:

``POST /api/v1/campaigns/{campaign_id}/generate-qr``

It is authenticated and always scopes the campaign to the caller's
organization.  The response is a print-ready PDF with one A4 poster per
recipient and a unique tracking URL in every QR code.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, Organization, User
from app.schemas import QRPosterRequest
from app.services.quishing_service import (
    QR_PRECEPTS,
    PosterRecipient,
    build_poster_pack,
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
    """Return a channel config with optional poster copy overrides applied."""
    config = dict(channel_config or {})
    qr_config = config.get("qr")
    qr_values = dict(qr_config) if isinstance(qr_config, dict) else {}
    if payload is not None:
        for field in ("headline", "body", "footer", "pretext_key"):
            value = getattr(payload, field, None)
            if value is not None and str(value).strip():
                qr_values[field] = str(value).strip()
        if qr_values.get("pretext_key") not in QR_PRECEPTS:
            # Keep custom copy but do not persist an unknown preset key; the
            # service will fall back to the documented default.
            qr_values.pop("pretext_key", None)
    config["qr"] = qr_values
    return config


@router.post(
    "/{campaign_id}/generate-qr",
    summary="Generate printable quishing posters",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "A4 poster pack"},
        400: {"description": "Campaign is not a QR campaign or has no targets"},
        404: {"description": "Campaign not found"},
    },
)
async def generate_qr_posters(
    campaign_id: uuid.UUID,
    payload: QRPosterRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> Response:
    """Generate one unique QR poster per campaign recipient.

    Existing tracking rows are reused, so repeated downloads never invalidate a
    poster that has already been printed.  Missing rows are created and every
    QR encodes the recipient's unguessable tracking UUID.
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

    employee_ids: list[uuid.UUID] = []
    for raw in campaign.target_employee_ids or []:
        try:
            employee_ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    employee_ids = list(dict.fromkeys(employee_ids))
    if not employee_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one recipient before generating posters",
        )

    employees = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == campaign.organization_id,
                HumanAsset.id.in_(employee_ids),
            )
        )
    ).scalars().all()
    by_id = {employee.id: employee for employee in employees}
    ordered = [by_id[employee_id] for employee_id in employee_ids if employee_id in by_id]
    if not ordered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="None of the campaign recipients belong to this organization",
        )

    existing_rows = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().all()
    by_employee = {row.employee_id: row for row in existing_rows}

    settings = get_settings()
    base_url = settings.base_url.rstrip("/")
    recipients: list[PosterRecipient] = []
    for employee in ordered:
        tracking = by_employee.get(employee.id)
        if tracking is None:
            tracking = EmailTracking(
                campaign_id=campaign.id,
                employee_id=employee.id,
                template_id=campaign.template_id,
                channel="qr",
                provider="simulation",
            )
            db.add(tracking)
            await db.flush()
            by_employee[employee.id] = tracking
        else:
            # A draft campaign can switch channels.  Reuse the row (and its
            # UUID) rather than orphaning an already-printed poster.
            tracking.channel = "qr"
            tracking.provider = "simulation"
            tracking.template_id = campaign.template_id or tracking.template_id
        recipients.append(
            PosterRecipient(
                name=employee.full_name or employee.email,
                email=employee.email,
                tracking_uuid=str(tracking.tracking_uuid),
                tracking_url=f"{base_url}/simulation/qr/{tracking.tracking_uuid}",
            )
        )

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
            detail="Unable to generate the QR poster pack",
        ) from exc

    logger.info(
        "qr_posters_generated",
        campaign_id=str(campaign.id),
        organization_id=str(campaign.organization_id),
        recipients=len(recipients),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="campaign-{campaign.id}-qr-posters.pdf"'
            ),
            "Cache-Control": "no-store",
            "X-Poster-Count": str(len(recipients)),
        },
    )


__all__ = ["router"]
