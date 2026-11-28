"""Pretext template orchestration: AI first, curated fallback, then storage.

The AI engine (:meth:`app.services.ai_service.AIService.generate_pretext`) is
strict on purpose: a rejected or unavailable generation must never break a
campaign.  This module therefore:

1. asks the model for a pretext and validates its output;
2. on any failure (not configured, timeout, provider error, blocklisted text)
   falls back to a pre-approved template from the ``templates`` table, and only
   then to an in-code curated template;
3. stores every result in ``templates`` with the ``pretext_used`` analytics tag.

Stored bodies use the platform's own merge tokens (``{{tracking_url}}`` for
email, ``{{link}}`` for SMS/WhatsApp) instead of ``[TRACKING_LINK]``, so the
existing personaliser and click tracker work unchanged.
"""
from __future__ import annotations

import html
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import EmailTemplate, Organization
from app.schemas.ai import (
    PRETEXT_LABELS_AR,
    PretextGenerateRequest,
    PretextTemplateResult,
)
from app.services.ai_service import (
    SHORT_CHANNELS,
    TRACKING_PLACEHOLDER,
    AIService,
    AIServiceError,
    AITemplateRejected,
    validate_pretext_output,
)
from app.services.template_service import html_to_text

logger = get_logger(__name__)

#: Merge tokens a curated template may already contain.
_LINK_TOKENS = ("{{link}}", "{{tracking_url}}", "{{short_url}}")
#: Difficulty per trigger: familiarity is the subtlest, fear the bluntest.
_PRETEXT_DIFFICULTY: dict[str, int] = {
    "authority": 6,
    "urgency": 5,
    "familiarity": 7,
    "scarcity": 5,
    "fear": 4,
}
#: Variables the stored templates declare for the template editor.
_AVAILABLE_VARIABLES = [
    "first_name",
    "last_name",
    "department",
    "company_name",
    "job_title",
    "tracking_url",
    "link",
]

#: Last-resort Arabic copy, used only when the organization has no active
#: template for the channel.  Each entry stays inside the engine's length limits
#: and uses ``[TRACKING_LINK]`` like the generated text.
_STATIC_FALLBACK: dict[str, dict[str, str]] = {
    "authority": {
        "subject": "مراجعة عاجلة من الإدارة المالية",
        "email": (
            "مرحباً {{first_name}}،\n"
            "أرفقت لك النسخة المحدثة من تقرير الميزانية على نظام ERP الداخلي قبل "
            "اجتماع الإدارة.\n"
            "يرجى مراجعة البنود المعدلة وتأكيد الاستلام: [TRACKING_LINK]"
        ),
        "short": (
            "مرحباً {{first_name}}، الإدارة المالية طلبت مراجعة تقريرك على ERP الداخلي "
            "اليوم. يرجى تأكيد الاستلام: [TRACKING_LINK]"
        ),
    },
    "urgency": {
        "subject": "إجراء مطلوب قبل نهاية اليوم",
        "email": (
            "مرحباً {{first_name}}،\n"
            "تم تعليق بعض بيانات حسابك على بوابة الموارد البشرية HR-Portal لحين "
            "تأكيدها.\n"
            "يرجى استكمال الخطوة قبل إغلاق الدوام، وإلا سيُعاد إرسال الطلب غداً: "
            "[TRACKING_LINK]"
        ),
        "short": (
            "مرحباً {{first_name}}، تم تعليق بياناتك على HR-Portal ويُغلق الطلب الساعة 5. "
            "يرجى التأكيد الآن: [TRACKING_LINK]"
        ),
    },
    "familiarity": {
        "subject": "نسخة من محضر اجتماع القسم",
        "email": (
            "أهلاً {{first_name}}،\n"
            "جهزت نسخة من محضر اجتماع {{department}} على مساحة الفريق الداخلية، وفيها "
            "بند يخصك.\n"
            "لو تكرمت راجعها وأضف ملاحظتك قبل أن نرسلها للإدارة: [TRACKING_LINK]"
        ),
        "short": (
            "أهلاً {{first_name}}، رفعت محضر اجتماع {{department}} على مساحة الفريق وفيه "
            "بند يخصك. راجعه هنا: [TRACKING_LINK]"
        ),
    },
    "scarcity": {
        "subject": "مقاعد محدودة في برنامج التطوير الداخلي",
        "email": (
            "مرحباً {{first_name}}،\n"
            "فتحت الإدارة عدداً محدوداً من مقاعد برنامج التطوير المهني هذا الربع، "
            "والترشيح متاح لقسم {{department}}.\n"
            "إن رغبت بالترشيح يرجى تأكيد بياناتك خلال اليوم: [TRACKING_LINK]"
        ),
        "short": (
            "مرحباً {{first_name}}، بقيت مقاعد محدودة في برنامج التطوير لقسم "
            "{{department}}. أكد ترشيحك قبل الإغلاق: [TRACKING_LINK]"
        ),
    },
    "fear": {
        "subject": "تنبيه: محاولة دخول غير معتادة على حسابك",
        "email": (
            "مرحباً {{first_name}}،\n"
            "رصد نظام الحماية محاولة دخول غير معتادة على حسابك من جهاز جديد، وتم تعليق "
            "الجلسة مؤقتاً.\n"
            "يرجى تأكيد أنك صاحب المحاولة لاستعادة الوصول: [TRACKING_LINK]"
        ),
        "short": (
            "مرحباً {{first_name}}، رُصد دخول غير معتاد على حسابك وتم تعليق الجلسة. أكد أنك "
            "صاحب المحاولة: [TRACKING_LINK]"
        ),
    },
}


def _static_result(request: PretextGenerateRequest) -> PretextTemplateResult:
    """Return the curated fallback template for this trigger and channel."""
    definition = _STATIC_FALLBACK[request.pretext.value]
    body = definition["email"] if request.channel == "email" else definition["short"]
    return PretextTemplateResult(
        subject=definition["subject"],
        body_text=body,
        pretext_used=request.pretext,
        channel=request.channel,
        source="fallback",
        provider="static",
        model="curated",
    )


def _replace_link_tokens(text: str) -> str:
    """Normalise curated merge tokens back to the engine's placeholder."""
    normalised = text
    for token in _LINK_TOKENS:
        normalised = normalised.replace(token, TRACKING_PLACEHOLDER)
    return normalised.strip()


async def _candidate_templates(
    db: AsyncSession, organization_id: uuid.UUID, channel: str
) -> list[EmailTemplate]:
    """Return the tenant's active templates for ``channel``, best first.

    Built-in templates and the requested department win, so the fallback feels
    relevant instead of generic.
    """
    rows = list(
        (
            await db.execute(
                select(EmailTemplate)
                .where(
                    EmailTemplate.organization_id == organization_id,
                    EmailTemplate.channel == channel,
                    EmailTemplate.is_active.is_(True),
                )
                .order_by(EmailTemplate.is_built_in.desc(), EmailTemplate.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return rows


async def load_fallback_result(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    request: PretextGenerateRequest,
) -> PretextTemplateResult:
    """Pick a pre-approved template, then the in-code curated copy."""
    rows = await _candidate_templates(db, organization_id, request.channel)
    department = request.department.strip().lower()
    ordered = sorted(
        rows,
        key=lambda row: 0
        if (row.target_department or "").strip().lower() in {department, "all"}
        else 1,
    )
    for row in ordered:
        subject = (row.subject or "").strip()
        body = _replace_link_tokens(html_to_text(row.body_html or ""))
        if not subject or not body:
            continue
        try:
            validate_pretext_output(
                subject=subject,
                body_text=body,
                channel=request.channel,
                # Curated copy is trusted for length on the email channel; an
                # over-long SMS would still be truncated by the gateway.
                enforce_length=False,
            )
        except AITemplateRejected as exc:
            logger.info(
                "pretext_fallback_candidate_skipped",
                template_id=str(row.id),
                reason=str(exc)[:200],
            )
            continue
        return PretextTemplateResult(
            subject=subject,
            body_text=body,
            pretext_used=request.pretext,
            channel=request.channel,
            source="fallback",
            provider="database",
            model=(row.name or "")[:120],
        )
    return _static_result(request)


def build_stored_body(result: PretextTemplateResult) -> str:
    """Render a validated pretext into the HTML stored in ``templates``.

    Email bodies become paragraphs whose ``[TRACKING_LINK]`` turns into the
    tracked anchor the personaliser rewrites; short channels store plain text
    with the ``{{link}}`` alias the launcher swaps for the short URL.
    """
    if result.channel in SHORT_CHANNELS:
        escaped = html.escape(result.body_text, quote=False).replace(
            TRACKING_PLACEHOLDER, "{{link}}"
        )
        return f"<p>{escaped}</p>"

    anchor = (
        '<a href="{{tracking_url}}" style="color:#0b5fff;font-weight:700;'
        'text-decoration:none;">مراجعة التفاصيل</a>'
    )
    paragraphs = [
        chunk.strip() for chunk in result.body_text.split("\n") if chunk.strip()
    ]
    body = "".join(
        f'<p style="margin:0 0 14px;">'
        f"{html.escape(chunk, quote=False).replace(TRACKING_PLACEHOLDER, anchor)}</p>"
        for chunk in paragraphs
    )
    return body or f"<p>{html.escape(result.body_text, quote=False)}</p>"


async def persist_pretext_template(
    db: AsyncSession,
    *,
    organization: Organization,
    request: PretextGenerateRequest,
    result: PretextTemplateResult,
) -> PretextTemplateResult:
    """Save the generated template and tag it with ``pretext_used``."""
    label = PRETEXT_LABELS_AR.get(result.pretext_used.value, result.pretext_used.value)
    name = (
        f"{label} · {request.department.strip()} · {request.channel.upper()} · "
        f"{request.employee_name.strip()}"
    )[:255]
    template = EmailTemplate(
        organization_id=organization.id,
        channel=request.channel,
        name=name,
        subject=result.subject[:500],
        body_html=build_stored_body(result),
        design_json=None,
        target_department=request.department.strip()[:50] or None,
        pretext_used=result.pretext_used.value,
        difficulty_level=_PRETEXT_DIFFICULTY.get(result.pretext_used.value, 5),
        available_variables=list(_AVAILABLE_VARIABLES),
        is_built_in=False,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    logger.info(
        "pretext_template_stored",
        organization_id=str(organization.id),
        template_id=str(template.id),
        pretext=result.pretext_used.value,
        channel=request.channel,
        source=result.source,
    )
    return result.model_copy(update={"template_id": template.id})


async def generate_pretext_template(
    db: AsyncSession,
    *,
    organization: Organization,
    request: PretextGenerateRequest,
    service: AIService | None = None,
) -> PretextTemplateResult:
    """Generate, validate, fall back and store one pretext template."""
    engine = service or AIService()
    try:
        result = await engine.generate_pretext(request)
    except (AIServiceError, AITemplateRejected) as exc:
        logger.warning(
            "pretext_generation_fell_back",
            organization_id=str(organization.id),
            reason=type(exc).__name__,
            error=str(exc)[:300],
        )
        result = await load_fallback_result(
            db, organization_id=organization.id, request=request
        )

    if not request.save:
        return result
    return await persist_pretext_template(
        db, organization=organization, request=request, result=result
    )


__all__ = [
    "build_stored_body",
    "generate_pretext_template",
    "load_fallback_result",
    "persist_pretext_template",
]
