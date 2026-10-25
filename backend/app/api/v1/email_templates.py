"""Email template endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, get_organization_or_404, rate_limit, require_roles
from app.logging_config import get_logger
from app.models import DEFAULT_VARIABLES, EmailTemplate, HumanAsset, User
from app.schemas import (
    EmailTemplateCreate,
    EmailTemplatePublic,
    EmailTemplateUpdate,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
)
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
    """Create a custom template."""
    template = EmailTemplate(
        organization_id=org_id,
        name=payload.name,
        subject=payload.subject,
        body_html=payload.body_html,
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
    deleted, but their copy may be adjusted.
    """
    template = await _get_template(db, org_id, template_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
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
