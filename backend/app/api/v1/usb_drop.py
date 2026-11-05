"""Safe USB-drop PDF endpoint.

The USB channel is delivered physically: an operator downloads a standard PDF,
copies it to authorized USB drives and drops them during an approved awareness
exercise.  The PDF contains no executable content.  Every document carries a
unique tracking QR that records ``usb_opened`` and redirects the recipient to
the micro-training page.

``POST /api/v1/campaigns/{campaign_id}/generate-usb-pdf``
"""
from __future__ import annotations

from datetime import datetime, timezone

import io
import uuid
import zipfile

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTracking, HumanAsset, Organization, User
from app.schemas import USBPDFRequest
from app.services.usb_drop_service import (
    HTML_DOCUMENT_NAME,
    USBDropRecipient,
    build_usb_drop_pack,
    build_usb_html,
    content_disposition,
    content_disposition_html,
    resolve_usb_copy,
    safe_document_name,
    safe_html_name,
)

logger = get_logger(__name__)
router = APIRouter(
    prefix="/campaigns",
    tags=["usb-drop"],
    dependencies=[Depends(rate_limit(scope="campaigns"))],
)


def _merge_usb_overrides(
    channel_config: dict | None,
    payload: USBPDFRequest | None,
) -> dict:
    """Return a channel config with optional USB document metadata applied."""
    config = dict(channel_config or {})
    raw = config.get("usb")
    usb_values = dict(raw) if isinstance(raw, dict) else {}
    if payload is not None:
        if payload.document_name is not None and payload.document_name.strip():
            usb_values["document_name"] = safe_document_name(payload.document_name)
        if payload.month_label is not None and payload.month_label.strip():
            usb_values["month_label"] = payload.month_label.strip()[:80]
    config["usb"] = usb_values
    return config


async def _load_usb_recipients(
    campaign_id: uuid.UUID,
    employee_id: uuid.UUID | None,
    db: AsyncSession,
    user: User,
) -> tuple[EmailCampaign, Organization, list[USBDropRecipient]]:
    """Validate a USB campaign and materialise deterministic tracking links.

    Tracking rows are reused across downloads so an already-copied document
    never loses its attribution.  The helper does not commit; the caller owns
    the transaction and any channel-config updates.
    """
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    if (campaign.channel or "").strip().lower() != "usb":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="USB documents can only be generated for a usb campaign",
        )

    organization = await db.get(Organization, campaign.organization_id)
    if organization is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    target_ids: list[uuid.UUID] = []
    for raw in campaign.target_employee_ids or []:
        try:
            target_ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    target_ids = list(dict.fromkeys(target_ids))
    if not target_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one recipient before generating the USB document",
        )
    if employee_id is not None:
        if employee_id not in target_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected employee is not a target of this campaign",
            )
        target_ids = [employee_id]

    employees = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == campaign.organization_id,
                HumanAsset.id.in_(target_ids),
            )
        )
    ).scalars().all()
    by_id = {employee.id: employee for employee in employees}
    ordered = [by_id[target_id] for target_id in target_ids if target_id in by_id]
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

    base_url = get_settings().base_url.rstrip("/")
    recipients: list[USBDropRecipient] = []
    for employee in ordered:
        tracking = by_employee.get(employee.id)
        if tracking is None:
            tracking = EmailTracking(
                campaign_id=campaign.id,
                employee_id=employee.id,
                template_id=campaign.template_id,
                channel="usb",
                provider="simulation",
            )
            db.add(tracking)
            await db.flush()
            by_employee[employee.id] = tracking
        else:
            # A draft campaign can switch channels. Reuse the row (and its UUID)
            # rather than orphaning a document that is already on a USB drive.
            tracking.channel = "usb"
            tracking.provider = "simulation"
            tracking.template_id = campaign.template_id or tracking.template_id
        recipients.append(
            USBDropRecipient(
                name=employee.full_name or employee.email,
                email=employee.email,
                tracking_uuid=str(tracking.tracking_uuid),
                tracking_url=f"{base_url}/api/v1/track/usb/{tracking.tracking_uuid}",
                department=employee.department or "",
            )
        )
    return campaign, organization, recipients


@router.post(
    "/{campaign_id}/generate-usb-pdf",
    summary="Generate safe USB-drop awareness documents",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "USB PDF pack"},
        400: {"description": "Campaign is not a USB campaign or has no targets"},
        404: {"description": "Campaign not found"},
    },
)
async def generate_usb_pdf(
    campaign_id: uuid.UUID,
    payload: USBPDFRequest | None = Body(default=None),
    employee_id: uuid.UUID | None = Query(
        default=None,
        description="Optional single-recipient filter for one physical USB drive",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> Response:
    """Generate one unique USB-awareness page per campaign recipient.

    Existing tracking rows are reused, so a repeated download never invalidates
    a document that has already been copied to a USB drive.  When ``employee_id``
    is supplied, only that recipient's page is generated — useful when the
    operator prepares one drive per employee.
    """
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    if (campaign.channel or "").strip().lower() != "usb":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="USB documents can only be generated for a usb campaign",
        )

    organization = await db.get(Organization, campaign.organization_id)
    if organization is None:  # pragma: no cover - FK guarantees existence
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    target_ids: list[uuid.UUID] = []
    for raw in campaign.target_employee_ids or []:
        try:
            target_ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    target_ids = list(dict.fromkeys(target_ids))
    if not target_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one recipient before generating the USB document",
        )
    if employee_id is not None:
        if employee_id not in target_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected employee is not a target of this campaign",
            )
        target_ids = [employee_id]

    employees = (
        await db.execute(
            select(HumanAsset).where(
                HumanAsset.organization_id == campaign.organization_id,
                HumanAsset.id.in_(target_ids),
            )
        )
    ).scalars().all()
    by_id = {employee.id: employee for employee in employees}
    ordered = [by_id[target_id] for target_id in target_ids if target_id in by_id]
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
    recipients: list[USBDropRecipient] = []
    for employee in ordered:
        tracking = by_employee.get(employee.id)
        if tracking is None:
            tracking = EmailTracking(
                campaign_id=campaign.id,
                employee_id=employee.id,
                template_id=campaign.template_id,
                channel="usb",
                provider="simulation",
            )
            db.add(tracking)
            await db.flush()
            by_employee[employee.id] = tracking
        else:
            # A draft campaign can switch channels. Reuse the row (and its UUID)
            # rather than orphaning a document that is already on a USB drive.
            tracking.channel = "usb"
            tracking.provider = "simulation"
            tracking.template_id = campaign.template_id or tracking.template_id
        recipients.append(
            USBDropRecipient(
                name=employee.full_name or employee.email,
                email=employee.email,
                tracking_uuid=str(tracking.tracking_uuid),
                tracking_url=f"{base_url}/api/v1/track/usb/{tracking.tracking_uuid}",
                department=employee.department or "",
            )
        )

    campaign.channel_config = _merge_usb_overrides(campaign.channel_config, payload)
    await db.commit()

    try:
        pdf_bytes = build_usb_drop_pack(
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
            "usb_pdf_generation_failed",
            campaign_id=str(campaign.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate the USB awareness document",
        ) from exc

    copy = resolve_usb_copy(campaign.channel_config)
    logger.info(
        "usb_pdf_generated",
        campaign_id=str(campaign.id),
        organization_id=str(campaign.organization_id),
        recipients=len(recipients),
        document_name=copy.document_name,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(copy.document_name),
            "Cache-Control": "no-store",
            "X-Document-Count": str(len(recipients)),
        },
    )


@router.post(
    "/{campaign_id}/generate-usb-html",
    summary="Generate the safe HTML USB-drop artefact",
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {}, "application/zip": {}},
            "description": "Single Arabic HTML file, or a ZIP for multiple recipients",
        },
        400: {"description": "Campaign is not a USB campaign or has no targets"},
        404: {"description": "Campaign not found"},
    },
)
async def generate_usb_html(
    campaign_id: uuid.UUID,
    employee_id: uuid.UUID | None = Query(
        default=None,
        description="Optional single-recipient filter for one physical USB drive",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> Response:
    """Generate ``الرواتب_السرية.html`` for an approved USB-drop exercise.

    A single recipient receives the exact Arabic filename.  If the campaign has
    multiple recipients and no ``employee_id`` filter is supplied, the response
    is a ZIP containing one uniquely attributed HTML file per employee so an
    operator never puts the same tracking identity on every drive.

    The HTML contains no executable, no macro, no auto-run instruction and no
    local-file access.  It calls ``GET /api/v1/track/usb/{uuid}`` once on open
    and then shows the required red awareness warning.
    """
    campaign, organization, recipients = await _load_usb_recipients(
        campaign_id, employee_id, db, user
    )
    base_url = get_settings().base_url.rstrip("/")
    support_email = organization.brand_support_email

    def render(recipient: USBDropRecipient) -> bytes:
        return build_usb_html(
            organization=organization,
            recipient=recipient,
            training_url=(
                f"{base_url}/training/{recipient.tracking_uuid}?channel=usb"
            ),
            support_email=support_email,
        )

    await db.commit()
    try:
        if employee_id is not None or len(recipients) == 1:
            recipient = recipients[0]
            html_bytes = render(recipient)
            logger.info(
                "usb_html_generated",
                campaign_id=str(campaign.id),
                organization_id=str(campaign.organization_id),
                recipients=1,
                document_name=HTML_DOCUMENT_NAME,
            )
            return Response(
                content=html_bytes,
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": content_disposition_html(),
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "X-Document-Count": "1",
                    "X-Tracking-UUID": recipient.tracking_uuid,
                },
            )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, recipient in enumerate(recipients, start=1):
                label = (recipient.name or recipient.email or f"employee-{index}")[:40]
                folder = safe_html_name(
                    f"{label}-{recipient.tracking_uuid[:8]}"
                ).removesuffix(".html")
                # Every employee keeps the exact required file name.  A
                # per-recipient folder prevents collisions in the ZIP while
                # preserving attribution on each copied USB drive.
                entry_name = f"{folder}/{HTML_DOCUMENT_NAME}"
                archive.writestr(entry_name, render(recipient))
        logger.info(
            "usb_html_pack_generated",
            campaign_id=str(campaign.id),
            organization_id=str(campaign.organization_id),
            recipients=len(recipients),
        )
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="usb_html_pack.zip"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Document-Count": str(len(recipients)),
            },
        )
    except Exception as exc:  # noqa: BLE001 - explicit 500, never corrupt HTML
        logger.error(
            "usb_html_generation_failed",
            campaign_id=str(campaign.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate the USB HTML awareness file",
        ) from exc


@router.get(
    "/{campaign_id}/generate-test-payload",
    summary="Generate safe USB endpoint training test assets",
)
@router.post(
    "/{campaign_id}/generate-test-payload",
    summary="Generate safe USB endpoint training test assets",
)
async def generate_test_payload(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Generate safe, authorized USB awareness test assets for physical simulation.

    Includes:
    1. Company_Security_Notice.url (Windows internet shortcut)
    2. فحص_الوعي_الأمني.bat (Safe batch file capturing hostname & username)
    3. اقرأني_إشعار_تدريب_أمني.txt (Training disclaimer and guidelines)
    """
    import base64

    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    if (campaign.channel or "").strip().lower() != "usb":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="USB test payload is only valid for usb campaigns",
        )

    organization = await db.get(Organization, campaign.organization_id)
    org_name = organization.name if organization else "Enterprise"

    tracking = await db.scalar(
        select(EmailTracking)
        .where(
            EmailTracking.campaign_id == campaign.id,
            EmailTracking.channel == "usb",
        )
        .order_by(EmailTracking.created_at.asc())
        .limit(1)
    )

    if tracking is None:
        tracking = EmailTracking(
            campaign_id=campaign.id,
            employee_id=None,
            tracking_uuid=uuid.uuid4(),
            channel="usb",
        )
        db.add(tracking)
        await db.flush()
        await db.commit()

    tracking_uuid = str(tracking.tracking_uuid)
    settings = get_settings()
    base_url = settings.base_url.rstrip("/")

    # Safe Asset 1: Internet Shortcut (.url)
    shortcut_content = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}
IconIndex=0
"""

    # Safe Asset 2: Safe Batch Launcher (.bat) capturing %COMPUTERNAME% & %USERNAME%
    bat_content = f"""@echo off
title HUMINT Shield - Physical Security Training Checkpoint
chcp 65001 >nul
cls
echo =======================================================================
echo   [HUMINT SHIELD] تمرين المحاكاة والتوعية الأمنية الميدانية
echo   Authorized Enterprise Security Training Simulation Checkpoint
echo =======================================================================
echo.
echo جاري فحص استجابة النظام وتسجيل حالة التوعية الميدانية...
echo System endpoint verified. Launching awareness checkpoint...
echo.
start "" "{base_url}/api/v1/track/usb/{tracking_uuid}?hostname=%COMPUTERNAME%&username=%USERNAME%"
timeout /t 3 >nul
exit
"""

    # Safe Asset 3: Training Disclaimer & Notice (.txt)
    disclaimer_content = f"""================================================================================
إشعار تدريب وتوعية أمنية معتمد (Authorized Security Awareness Simulation)
المؤسسة: {org_name}
الحملة: {campaign.name}
تاريخ الإصدار: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
================================================================================

تنبيه أمني هام للموظف / المستخدم:
هذا القرص والمحتويات المتواجدة بداخله هي جزء من تمرين محاكاة وتوعية أمنية معتمد ومصرح به
من قبل إدارة الأمن السيبراني (HUMINT Shield Physical Assessment).

الهدف من هذا التمرين:
قياس مستوى الجاهزية والوعي الوقائي لدى منسوبي المؤسسة ضد هجمات وسائط التخزين المجهولة (USB Drop Attacks)
والتأكد من عدم تشغيل أو إدخال أي وسائط خارجية غير مصرح بها.

إذا قمت بتوصيل هذا القرص أو فتح هذا الملف، يرجى التوجه فوراً إلى الرابط أدناه لاستكمال
جلسة التوعية التفاعلية وقراءة الإرشادات الأمنية الخاصة بالمؤسسة:
{base_url}/training/{tracking_uuid}?channel=usb

شكراً لتعاونكم الدائم في حماية أمن المؤسسة ومعلوماتها.
إدارة الأمن السيبراني
"""

    def _b64(content: str) -> str:
        return base64.b64encode(content.encode("utf-8")).decode("ascii")

    assets = [
        {
            "filename": "Company_Security_Notice.url",
            "content_base64": _b64(shortcut_content),
            "type": "shortcut",
            "size": len(shortcut_content),
            "description": "Windows Internet Shortcut directing to training tracker",
        },
        {
            "filename": "فحص_الوعي_الأمني.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "size": len(bat_content),
            "description": "Safe batch file capturing endpoint hostname and launching training page",
        },
        {
            "filename": "اقرأني_إشعار_تدريب_أمني.txt",
            "content_base64": _b64(disclaimer_content),
            "type": "notice",
            "size": len(disclaimer_content),
            "description": "Authorized training disclaimer and instructions",
        },
    ]

    return {
        "success": True,
        "campaign_id": str(campaign.id),
        "tracking_uuid": tracking_uuid,
        "organization_name": org_name,
        "assets_count": len(assets),
        "assets": assets,
    }


__all__ = ["router"]

