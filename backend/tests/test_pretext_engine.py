"""Tests for the pretext engine: prompt, blocklist, fallback and tagging."""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.api.v1.ai import get_ai_service
from app.config import Settings
from app.models import EmailTemplate
from app.schemas.ai import PretextGenerateRequest, PretextTemplateResult, PretextType
from app.services.ai_service import (
    AIProviderError,
    AIService,
    AITemplateRejected,
    build_pretext_prompt,
    validate_pretext_output,
)
from app.services.pretext_service import generate_pretext_template, load_fallback_result

BASE = "/api/v1/ai"

VALID_BODY = (
    "مرحباً أحمد، أرفقت لك النسخة المحدثة من تقرير الميزانية على نظام ERP الداخلي. "
    "يرجى تأكيد الاستلام: [TRACKING_LINK]"
)


def _request(**overrides: object) -> PretextGenerateRequest:
    """Build a valid request, overriding individual fields per test."""
    payload: dict[str, object] = {
        "employee_name": "Ahmed",
        "job_title": "Accountant",
        "department": "Finance",
        "company_name": "Acme Corp",
        "industry": "Banking",
        "pretext": "authority",
        "channel": "email",
    }
    payload.update(overrides)
    return PretextGenerateRequest(**payload)


def _settings(**overrides: object) -> Settings:
    """Provider settings pointing at a mock endpoint."""
    values: dict[str, object] = {
        "llm_provider": "openai",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "llm_fallback_models": "",
        "llm_base_url": "https://llm.example.test/v1",
    }
    values.update(overrides)
    return Settings(**values)


class _BrokenService:
    """Provider stand-in that always fails, to exercise the fallback path."""

    async def generate_pretext(self, request: PretextGenerateRequest) -> PretextTemplateResult:
        raise AIProviderError("provider timed out")


class _FixedService:
    """Provider stand-in that returns a valid, deterministic template."""

    def __init__(self, pretext: str = "authority") -> None:
        self.pretext = pretext

    async def generate_pretext(self, request: PretextGenerateRequest) -> PretextTemplateResult:
        return PretextTemplateResult(
            subject="تحديث تقرير الميزانية",
            body_text=VALID_BODY,
            pretext_used=PretextType(self.pretext),
            channel=request.channel,
            source="ai",
            provider="openai",
            model="test-model",
        )


# --------------------------------------------------------------------------- #
# Prompt contract
# --------------------------------------------------------------------------- #
def test_prompt_injects_every_parameter_and_rule() -> None:
    """The English prompt carries the exact inputs and the six rules."""
    prompt = build_pretext_prompt(
        employee_name="Ahmed",
        job_title="Accountant",
        department="Finance",
        company_name="Acme Corp",
        industry="Banking",
        pretext="authority",
        channel="email",
    )
    assert prompt.startswith("You are a Senior Social Engineer creating a training pretext.")
    for token in (
        "Ahmed",
        "Accountant",
        "Finance",
        "Acme Corp",
        "Banking",
        "Authority",
        "Email",
        "1. Use natural corporate tone and open with مرحباً or أهلاً",
        "Max length: 120 words",
        "[TRACKING_LINK]",
        "Return JSON only with keys: subject, body_text, pretext_used.",
    ):
        assert token in prompt


def test_prompt_switches_limit_for_short_channels() -> None:
    """SMS/WhatsApp get a character limit instead of a word limit."""
    prompt = build_pretext_prompt(
        employee_name="Sara",
        job_title="System Administrator",
        department="IT",
        company_name="Acme Corp",
        industry="Technology",
        pretext="urgency",
        channel="sms",
        language="ar-SA",
    )
    assert "SMS" in prompt
    assert "Max length: 160 characters" in prompt
    assert "Arabic (Saudi)" in prompt
    assert "Urgency" in prompt


# --------------------------------------------------------------------------- #
# Blocklist / length validation
# --------------------------------------------------------------------------- #
def test_blocklist_rejects_urls_html_and_active_content() -> None:
    """Real URLs, markup and handlers are rejected before anything is stored."""
    with pytest.raises(AITemplateRejected, match="real URL"):
        validate_pretext_output(
            subject="تحديث",
            body_text=f"سجّل من https://evil.example ثم {VALID_BODY}",
            channel="email",
        )
    with pytest.raises(AITemplateRejected, match="HTML markup"):
        validate_pretext_output(
            subject="تحديث",
            body_text=f"<b>{VALID_BODY}</b>",
            channel="email",
        )
    with pytest.raises(AITemplateRejected, match="active content"):
        validate_pretext_output(
            subject="تحديث",
            body_text=f'<a onclick="steal()">{VALID_BODY}</a>',
            channel="email",
        )
    with pytest.raises(AITemplateRejected, match="must contain"):
        validate_pretext_output(subject="تحديث", body_text="مرحباً أحمد", channel="email")
    with pytest.raises(AITemplateRejected, match="robotic phrase"):
        validate_pretext_output(
            subject="تحديث",
            body_text="عزيزي المستخدم، يرجى مراجعة بياناتك: [TRACKING_LINK]",
            channel="email",
        )


def test_length_limits_are_enforced_per_channel() -> None:
    """Email is capped at 120 words, SMS/WhatsApp at 160 characters."""
    # 121 repeated words plus the placeholder token tripped the 120-word cap.
    long_email = " ".join(["كلمة"] * 121) + " [TRACKING_LINK]"
    with pytest.raises(AITemplateRejected, match="the limit is 120"):
        validate_pretext_output(subject="ت", body_text=long_email, channel="email")

    long_sms = ("ا" * 150) + " [TRACKING_LINK]"
    with pytest.raises(AITemplateRejected, match="characters"):
        validate_pretext_output(subject="ت", body_text=long_sms, channel="sms")

    # A curated email is trusted for length when the flag is off, but a short
    # channel is always capped.
    validate_pretext_output(
        subject="ت", body_text=long_email, channel="email", enforce_length=False
    )
    with pytest.raises(AITemplateRejected):
        validate_pretext_output(
            subject="ت", body_text=long_sms, channel="whatsapp", enforce_length=False
        )


# --------------------------------------------------------------------------- #
# Provider round-trip
# --------------------------------------------------------------------------- #
async def test_generate_pretext_parses_and_validates_provider_json() -> None:
    """A well-formed provider answer becomes a validated template."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["prompt"] = body["messages"][1]["content"]
        content = json.dumps(
            {
                "subject": "تحديث تقرير الميزانية",
                "body_text": VALID_BODY,
                "pretext_used": "authority",
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={"model": "test-model", "choices": [{"message": {"content": content}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AIService(_settings(), client=client)
        result = await service.generate_pretext(_request())

    assert "You are a Senior Social Engineer" in str(seen["prompt"])
    assert "Acme Corp" in str(seen["prompt"])
    assert result.source == "ai"
    assert result.pretext_used is PretextType.authority
    assert "[TRACKING_LINK]" in result.body_text
    assert result.template_id is None


async def test_generate_pretext_rejects_blocklisted_provider_output() -> None:
    """A model that smuggles a real URL never produces a usable template."""

    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "subject": "تحديث",
                "body_text": "راجع الرابط https://evil.example قبل نهاية اليوم",
                "pretext_used": "authority",
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AIService(_settings(), client=client)
        with pytest.raises(AITemplateRejected, match="real URL"):
            await service.generate_pretext(_request())


async def test_unconfigured_provider_is_explicit() -> None:
    """No key means no fabricated template."""
    service = AIService(
        Settings(llm_provider="openai", llm_api_key="", llm_model="", llm_base_url="")
    )
    from app.services.ai_service import AIServiceNotConfigured

    with pytest.raises(AIServiceNotConfigured):
        await service.generate_pretext(_request())


# --------------------------------------------------------------------------- #
# Fallback and persistence
# --------------------------------------------------------------------------- #
async def test_ai_failure_falls_back_and_tags_the_saved_template(db, organization) -> None:
    """A provider timeout still yields a saved template with ``pretext_used``."""
    result = await generate_pretext_template(
        db,
        organization=organization,
        request=_request(pretext="urgency", channel="sms"),
        service=_BrokenService(),
    )

    assert result.source == "fallback"
    assert result.channel == "sms"
    assert result.template_id is not None

    stored = await db.get(EmailTemplate, result.template_id)
    assert stored is not None
    assert stored.pretext_used == "urgency"
    assert stored.channel == "sms"
    assert stored.is_built_in is False


async def test_fallback_prefers_a_database_template(
    db, organization, builtin_templates
) -> None:
    """Pre-approved rows in ``templates`` are reused before curated copy."""
    result = await load_fallback_result(
        db, organization_id=organization.id, request=_request(channel="email")
    )
    assert result.source == "fallback"
    assert result.provider in {"database", "static"}
    if result.provider == "database":
        assert result.model in {row.name for row in builtin_templates}


async def test_fallback_is_static_when_no_template_exists(db, organization) -> None:
    """Without any stored template the curated copy keeps the campaign alive."""
    result = await load_fallback_result(
        db, organization_id=organization.id, request=_request(pretext="fear", channel="whatsapp")
    )
    assert result.source == "fallback"
    assert result.provider == "static"
    # The curated copy must itself satisfy the engine contract.
    validate_pretext_output(
        subject=result.subject, body_text=result.body_text, channel="whatsapp"
    )


async def test_endpoint_stores_template_and_uses_tenant_industry(
    client, app, db, organization, auth_headers
) -> None:
    """The endpoint fills organization context and persists the result."""
    app.dependency_overrides[get_ai_service] = lambda: _FixedService()
    try:
        response = await client.post(
            f"{BASE}/pretext-template",
            headers=auth_headers,
            json={
                "employee_name": "Ahmed",
                "job_title": "Accountant",
                "department": "Finance",
                "pretext": "authority",
                "channel": "email",
            },
        )
    finally:
        app.dependency_overrides.pop(get_ai_service, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "ai"
    assert body["pretext_used"] == "authority"
    assert body["template_id"]

    rows = list(
        (
            await db.execute(
                select(EmailTemplate).where(EmailTemplate.pretext_used == "authority")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert "{{tracking_url}}" in rows[0].body_html
    assert "http" not in rows[0].body_html.replace("{{tracking_url}}", "")
