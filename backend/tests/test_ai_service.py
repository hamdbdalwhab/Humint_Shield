"""Tests for the AI template service and its security boundaries."""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.ai_service import (
    AIProviderError,
    AIService,
    AIServiceNotConfigured,
    _extract_json,
    sanitize_generated_html,
    sanitize_generated_text,
)


def test_sanitizer_removes_active_content() -> None:
    """Scripts, iframes, event handlers and javascript URLs are removed."""
    hostile = (
        '<div onclick="steal()">Hello</div>'
        '<script>alert(1)</script>'
        '<iframe src="https://evil.example"></iframe>'
        '<a href="javascript:alert(2)">Click</a>'
        '<object data="x"></object>'
    )
    cleaned = sanitize_generated_html(hostile)
    assert "script" not in cleaned.lower()
    assert "iframe" not in cleaned.lower()
    assert "onclick" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "object" not in cleaned.lower()
    assert "Hello" in cleaned
    assert 'href="#"' in cleaned


def test_extract_json_accepts_markdown_fences() -> None:
    """Models often wrap JSON in Markdown fences; the parser tolerates it."""
    assert _extract_json('```json\n{"subject": "Hi"}\n```') == {"subject": "Hi"}
    with pytest.raises(AIProviderError):
        _extract_json("not json")
    with pytest.raises(AIProviderError):
        _extract_json("[1, 2, 3]")


def test_extract_json_strips_reasoning_block() -> None:
    """Reasoning models may emit a think block before the JSON payload."""
    content = (
        "\x3cthink\x3eThe user wants {not: json}.\x3c/think\x3e\n"
        '{"subject": "Hi"}'
    )
    assert _extract_json(content) == {"subject": "Hi"}


def test_plain_text_body_is_escaped_before_wrapping() -> None:
    """Model text cannot inject markup into the fixed email shell."""
    cleaned = sanitize_generated_text('<b>Hello</b> & "team"\n\n<script>x</script>')
    assert "<b>" not in cleaned
    assert "<script>" not in cleaned
    assert "&amp;" in cleaned
    assert "&quot;" not in cleaned


async def test_missing_key_is_explicit_not_a_mock_template() -> None:
    """An unconfigured provider returns an error and never fabricated content."""
    settings = Settings(
        llm_provider="openai",
        llm_api_key="",
        llm_model="",
        llm_base_url="",
    )
    service = AIService(settings)
    with pytest.raises(AIServiceNotConfigured) as exc:
        await service.generate_template(
            organization_industry="Technology",
            target_department="Finance",
            scenario="Urgent invoice",
        )
    assert "LLM_API_KEY" in str(exc.value)


async def test_generate_template_validates_and_sanitizes() -> None:
    """A valid provider response is parsed, sanitized and normalized."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        content = json.dumps(
            {
                "subject": "Urgent:\n  Verify your account",
                "body_html": (
                    '<p>Hello {{first_name}}</p><script>alert(1)</script>'
                    '<div onclick="bad()">Review the document</div>'
                ),
                "difficulty_level": "8/10",
            }
        )
        return httpx.Response(
            200,
            json={"model": "test-model", "choices": [{"message": {"content": content}}]},
        )

    settings = Settings(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_fallback_models="",
        llm_base_url="https://llm.example.test/v1",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = AIService(settings, client=client)
        generated = await service.generate_template(
            organization_industry="Technology",
            target_department="Finance",
            scenario="Urgent invoice from a known vendor",
        )

    assert seen["url"] == "https://llm.example.test/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "test-model"
    assert "Technology" in body["messages"][1]["content"]
    assert "Finance" in body["messages"][1]["content"]
    assert generated.subject == "Urgent: Verify your account"
    assert generated.difficulty_level == 8
    assert "script" not in generated.body_html.lower()
    assert "onclick" not in generated.body_html.lower()
    assert "{{tracking_url}}" in generated.body_html
    assert generated.provider == "openai"
    assert generated.model == "test-model"


async def test_generate_template_falls_back_on_capacity_error() -> None:
    """A 429 from the primary model is retried on the configured fallback."""
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_models.append(body["model"])
        if body["model"] == "primary-model":
            return httpx.Response(
                429,
                json={"error": {"code": "model_concurrency"}},
            )
        content = json.dumps(
            {
                "subject": "تحديث كلمة المرور",
                "body_text": "مرحباً {{first_name}}، حدّث كلمة المرور في {{company_name}}.",
                "difficulty_level": 6,
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "fallback-model",
                "choices": [{"message": {"content": content}}],
            },
        )

    settings = Settings(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model="primary-model",
        llm_fallback_models="fallback-model",
        llm_base_url="https://llm.example.test/v1",
        llm_primary_timeout_seconds=5,
        llm_timeout_seconds=5,
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = AIService(settings, client=client)
        generated = await service.generate_template(
            organization_industry="Technology",
            target_department="السكرتارية",
            scenario="تحديث كلمة المرور",
        )

    assert seen_models == ["primary-model", "fallback-model"]
    assert generated.model == "fallback-model"
    assert generated.subject == "تحديث كلمة المرور"
    assert generated.difficulty_level == 6
    assert "{{first_name}}" in generated.body_html
    assert "{{company_name}}" in generated.body_html
    assert "{{tracking_url}}" in generated.body_html
    assert "مرحباً" in generated.body_html


async def test_provider_error_is_not_swallowed() -> None:
    """A provider 500 becomes an explicit AIProviderError."""
    settings = Settings(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_fallback_models="",
        llm_base_url="https://llm.example.test/v1",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = AIService(settings, client=client)
        with pytest.raises(AIProviderError) as exc:
            await service.generate_template(
                organization_industry="Technology",
                target_department="Finance",
                scenario="Invoice",
            )
    assert "HTTP 500" in str(exc.value)
    assert "upstream exploded" in str(exc.value)


async def test_invalid_json_is_rejected() -> None:
    """A malformed model response is an error, not an empty template."""
    settings = Settings(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_fallback_models="",
        llm_base_url="https://llm.example.test/v1",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "I cannot do that"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = AIService(settings, client=client)
        with pytest.raises(AIProviderError):
            await service.generate_template(
                organization_industry="Technology",
                target_department="Finance",
                scenario="Invoice",
            )
