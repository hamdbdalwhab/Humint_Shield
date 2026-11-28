"""AI-assisted template generation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import rate_limit, require_roles
from app.logging_config import get_logger
from app.models import Organization, User
from app.schemas.ai import (
    AIGeneratedTemplate,
    AIGenerateTemplateRequest,
    PretextGenerateRequest,
    PretextTemplateResult,
)
from app.services import pretext_service
from app.services.ai_service import (
    AIProviderError,
    AIService,
    AIServiceError,
    AIServiceNotConfigured,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(rate_limit(limit=10, window=60, scope="ai_generate"))],
)


def get_ai_service() -> AIService:
    """FastAPI dependency so tests can inject a deterministic provider."""
    return AIService()


@router.post(
    "/generate-template",
    response_model=AIGeneratedTemplate,
    status_code=status.HTTP_200_OK,
    summary="Generate a phishing-simulation template with an LLM",
)
async def generate_template(
    payload: AIGenerateTemplateRequest,
    user: User = Depends(require_roles("admin", "manager")),
    db: AsyncSession = Depends(get_db),
    service: AIService = Depends(get_ai_service),
) -> AIGeneratedTemplate:
    """Generate a template for the caller's own organization.

    The organization industry is read from the database, never from the request,
    so one tenant cannot ask the model to write for another tenant.  A missing
    provider configuration returns ``503`` with the exact missing environment
    variable names; the endpoint never fabricates a template.
    """
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The authenticated user is not attached to an organization",
        )
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    try:
        generated = await service.generate_template(
            organization_industry=organization.industry,
            target_department=payload.target_department,
            scenario=payload.scenario,
            channel=payload.channel,
        )
    except AIServiceNotConfigured as exc:
        logger.warning(
            "ai_generation_not_configured",
            organization_id=str(organization.id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (AIProviderError, AIServiceError) as exc:
        logger.warning(
            "ai_generation_failed",
            organization_id=str(organization.id),
            error=str(exc),
        )
        # Cloudflare replaces origin 5xx responses with its own HTML error page,
        # hiding the actionable provider message from the dashboard.  424 is a
        # client-visible failure that keeps the detail intact through the tunnel.
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=f"AI generation failed: {exc}",
        ) from exc

    logger.info(
        "ai_generation_request_completed",
        organization_id=str(organization.id),
        user_id=str(user.id),
        difficulty=generated.difficulty_level,
        provider=generated.provider,
    )
    return generated


@router.post(
    "/pretext-template",
    response_model=PretextTemplateResult,
    status_code=status.HTTP_200_OK,
    summary="Generate a psychology-driven training pretext template",
)
async def generate_pretext_template(
    payload: PretextGenerateRequest,
    user: User = Depends(require_roles("admin", "manager")),
    db: AsyncSession = Depends(get_db),
    service: AIService = Depends(get_ai_service),
) -> PretextTemplateResult:
    """Generate one pretext template for the caller's own organization.

    The organization name and industry default to the authenticated tenant, so
    a caller cannot ask the model to write for a different company.  Provider
    failures never surface to the caller: the engine falls back to a pre-approved
    template and the campaign continues.  Every result is stored in the
    ``templates`` table with its ``pretext_used`` analytics tag.
    """
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The authenticated user is not attached to an organization",
        )
    organization = await db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    request = payload.model_copy(
        update={
            "company_name": payload.company_name or organization.name,
            "industry": payload.industry or organization.industry or "general business",
        }
    )
    result = await pretext_service.generate_pretext_template(
        db, organization=organization, request=request, service=service
    )
    logger.info(
        "ai_pretext_request_completed",
        organization_id=str(organization.id),
        user_id=str(user.id),
        pretext=result.pretext_used.value,
        channel=result.channel,
        source=result.source,
        template_id=str(result.template_id) if result.template_id else None,
    )
    return result


__all__ = ["get_ai_service", "router"]
