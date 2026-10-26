"""Email template endpoints."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import DEFAULT_VARIABLES, EmailTemplate, HumanAsset, User
from app.schemas import (
    EmailDesign,
    EmailTemplateCreate,
    EmailTemplatePublic,
    EmailTemplateUpdate,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateTestSendRequest,
    TemplateTestSendResponse,
)
from app.services.brevo_service import BrevoService
from app.services.email_design import (
    branding_from_organization,
    compile_design_html,
    design_for_template,
    legacy_design_payload,
)
from app.services.html_sanitizer import sanitize_email_html
from app.services.template_service import TemplatePersonalizer

logger = get_logger(__name__)
router = APIRouter(
    prefix="/organizations/{org_id}/email-templates",
    tags=["email-templates"],
    dependencies=[Depends(rate_limit(scope="templates"))],
)


async def _get_template(
    db: AsyncSession, org_id: uuid.UUID, template_id: uuid.UUID
) -> EmailTemplate:
    """Load a template belonging to the organization.

    Raises:
        HTTPException: 404 when not found.
    """
    template = await db.get(EmailTemplate, template_id)
    if template is None or template.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


@router.get("", response_model=list[EmailTemplatePublic], summary="List email templates")
async def list_templates(
    org_id: uuid.UUID,
    search: str | None = Query(None, max_length=200),
    is_active: bool | None = Query(None),
    channel: str | None = Query(None, pattern="^(email|sms|whatsapp)$"),
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> list[EmailTemplatePublic]:
    """List the organization's templates, newest first.

    Args:
        org_id: Organization id.
        search: Optional case-insensitive filter on name/subject.
        is_active: Optional active-flag filter.
        channel: Optional channel filter (email/sms/whatsapp).
        db: Active session.
        organization: Resolved organization.
        user: Authenticated user.

    Returns:
        The matching templates.
    """
    filters = [EmailTemplate.organization_id == org_id]
    if search:
        pattern = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(EmailTemplate.name).like(pattern),
                func.lower(EmailTemplate.subject).like(pattern),
            )
        )
    if is_active is not None:
        filters.append(EmailTemplate.is_active.is_(is_active))
    if channel:
        filters.append(EmailTemplate.channel == channel)
    rows = (
        await db.execute(
            select(EmailTemplate)
            .where(*filters)
            .order_by(EmailTemplate.is_built_in.desc(), EmailTemplate.created_at.asc())
        )
    ).scalars().all()
    return [EmailTemplatePublic.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=EmailTemplatePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create an email template",
)
async def create_template(
    org_id: uuid.UUID,
    payload: EmailTemplateCreate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> EmailTemplatePublic:
    """Create a custom template from compiled HTML or a visual design."""
    settings = get_settings()
    branding = branding_from_organization(organization, settings.base_url)
    if payload.design_json is not None:
        design = payload.design_json
        body_html = compile_design_html(design, branding)
        design_json = design.model_dump(mode="json")
    else:
        body_html = sanitize_email_html(payload.body_html or "")
        design_json = legacy_design_payload(
            body_html, primary_color=branding.primary_color
        )
    template = EmailTemplate(
        organization_id=org_id,
        name=payload.name,
        subject=payload.subject,
        body_html=body_html,
        design_json=design_json,
        channel=payload.channel,
        difficulty_level=payload.difficulty_level,
        is_active=payload.is_active,
        is_built_in=False,
        available_variables=payload.available_variables or list(DEFAULT_VARIABLES),
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    logger.info("template_created", template_id=str(template.id), org_id=str(org_id))
    return EmailTemplatePublic.model_validate(template)


@router.get("/{template_id}", response_model=EmailTemplatePublic, summary="Get an email template")
async def get_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> EmailTemplatePublic:
    """Return a single template."""
    return EmailTemplatePublic.model_validate(await _get_template(db, org_id, template_id))


@router.get(
    "/{template_id}/design",
    response_model=EmailDesign,
    summary="Get the editable visual design for a template",
)
async def get_template_design(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> EmailDesign:
    """Return the visual design, wrapping legacy HTML automatically.

    This is the bridge that lets the thirteen pre-existing built-in templates
    open in the visual editor without rewriting their stored HTML first.
    """
    template = await _get_template(db, org_id, template_id)
    primary = getattr(organization, "brand_primary_color", None) or "#0F6CBD"
    return design_for_template(template, primary_color=primary)


@router.put("/{template_id}", response_model=EmailTemplatePublic, summary="Update an email template")
async def update_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: EmailTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> EmailTemplatePublic:
    """Update a template (built-in templates remain editable content-wise).

    Built-in templates keep their ``is_built_in`` flag so they can never be
    deleted, but their copy may be adjusted.  When a visual design is supplied,
    the backend recompiles and sanitises ``body_html`` so the stored compiled
    output always matches the editor source.
    """
    template = await _get_template(db, org_id, template_id)
    settings = get_settings()
    branding = branding_from_organization(organization, settings.base_url)
    design_supplied = "design_json" in payload.model_fields_set
    design = payload.design_json
    data = payload.model_dump(exclude_unset=True, exclude={"design_json"})

    if design_supplied:
        if design is None:
            # Explicitly clearing the visual source falls back to raw HTML.
            template.design_json = None
        else:
            template.body_html = compile_design_html(design, branding)
            template.design_json = design.model_dump(mode="json")
            data.pop("body_html", None)
    elif "body_html" in data:
        body_html = data.pop("body_html")
        if body_html is not None:
            body_html = sanitize_email_html(body_html)
            template.body_html = body_html
            template.design_json = legacy_design_payload(
                body_html, primary_color=branding.primary_color
            )

    for field, value in data.items():
        if value is not None:
            setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    logger.info("template_updated", template_id=str(template_id))
    return EmailTemplatePublic.model_validate(template)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom email template",
)
async def delete_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin")),
) -> None:
    """Delete a custom template.

    Raises:
        HTTPException: 400 when the template is built-in.
    """
    template = await _get_template(db, org_id, template_id)
    if template.is_built_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Built-in templates cannot be deleted",
        )
    await db.delete(template)
    await db.commit()
    logger.info("template_deleted", template_id=str(template_id))


@router.post(
    "/test-send",
    response_model=TemplateTestSendResponse,
    summary="Send the current visual design to the signed-in administrator",
)
async def send_test_template(
    org_id: uuid.UUID,
    payload: TemplateTestSendRequest,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(require_roles("admin", "manager")),
) -> TemplateTestSendResponse:
    """Render the unsaved editor state and send it to the admin's own inbox.

    Dummy employee values are used so merge tags are visible, but tracking is
    deliberately disabled: a test message must never create a real event.
    """
    if payload.channel != "email":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test sends are available for email templates only",
        )
    settings = get_settings()
    branding = branding_from_organization(organization, settings.base_url)
    if payload.design_json is not None:
        design = payload.design_json
        compiled = compile_design_html(design, branding)
        design_json = design.model_dump(mode="json")
    else:
        compiled = sanitize_email_html(payload.body_html or "")
        design_json = legacy_design_payload(
            compiled, primary_color=branding.primary_color
        )

    transient = SimpleNamespace(
        id="test-preview",
        subject=payload.subject,
        body_html=compiled,
        design_json=design_json,
    )
    dummy = SimpleNamespace(
        id="test-preview",
        first_name="سارة",
        last_name="العتيبي",
        email=user.email,
        department="الموارد البشرية",
        job_title="مديرة",
        manager_name="خالد الحربي",
        risk_profile={},
        behavioral_baseline={},
        device_profile={},
    )
    rendered = TemplatePersonalizer().personalize_test(
        transient, dummy, organization, settings.base_url
    )
    result = await BrevoService().send_email(
        to_email=user.email,
        subject=rendered["subject"],
        html_content=rendered["html_content"],
        to_name=user.email,
        correlation_id=f"test-send:{org_id}:{user.id}",
    )
    logger.info(
        "template_test_send",
        org_id=str(org_id),
        user_id=str(user.id),
        success=bool(result.get("success")),
    )
    return TemplateTestSendResponse(
        success=bool(result.get("success")),
        message_id=result.get("message_id"),
        error=result.get("error"),
        to_email=user.email,
        preview_html=rendered["html_content"],
    )


@router.post(
    "/{template_id}/preview",
    response_model=TemplatePreviewResponse,
    summary="Render a template for a specific employee",
)
async def preview_template(
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    payload: TemplatePreviewRequest,
    db: AsyncSession = Depends(get_db),
    organization=Depends(get_organization_or_404),
    user: User = Depends(get_current_user),
) -> TemplatePreviewResponse:
    """Personalise a template for an employee without sending anything.

    The rendered body uses the real tracking URLs (the pixel and click links
    are live but harmless until a campaign actually sends).

    Raises:
        HTTPException: 404 when the employee is not in the organization.
    """
    template = await _get_template(db, org_id, template_id)
    employee = await db.get(HumanAsset, payload.employee_id)
    if employee is None or employee.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    personalizer = TemplatePersonalizer()
    tracking_uuid = uuid.uuid4()
    rendered = personalizer.personalize(
        template=template,
        employee=employee,
        organization=organization,
        tracking_uuid=tracking_uuid,
    )
    text_rendered = personalizer.personalize_text(
        template=template,
        employee=employee,
        organization=organization,
        tracking_uuid=tracking_uuid,
    )
    missing = personalizer.validate_variables(template, employee)
    return TemplatePreviewResponse(
        subject=rendered["subject"],
        html_content=rendered["html_content"],
        text_content=text_rendered["text_content"],
        missing_variables=missing,
    )
