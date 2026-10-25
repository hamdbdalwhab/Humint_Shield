"""API tests for ``POST /api/v1/ai/generate-template``."""
from __future__ import annotations

from typing import Any

from app.api.v1.ai import get_ai_service
from app.config import Settings
from app.schemas.ai import AIGeneratedTemplate
from app.services.ai_service import AIService


class FakeAIService:
    """Deterministic provider used to test the HTTP wiring."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_template(self, **kwargs: Any) -> AIGeneratedTemplate:
        self.calls.append(kwargs)
        return AIGeneratedTemplate(
            subject="مرحباً {{first_name}}",
            body_html='<p>رسالة تدريب</p><a href="{{tracking_url}}">مراجعة</a>',
            difficulty_level=6,
            provider="test",
            model="test-model",
        )


async def test_ai_generation_requires_configuration(
    client, auth_headers, organization, app
) -> None:
    """Without a key the endpoint returns 503 with the missing variable name."""
    app.dependency_overrides[get_ai_service] = lambda: AIService(
        settings=Settings(llm_api_key="", llm_base_url="", llm_model="")
    )
    try:
        response = await client.post(
            "/api/v1/ai/generate-template",
            json={
                "target_department": "Finance",
                "scenario": "Urgent invoice from a known supplier",
            },
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_ai_service, None)
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


async def test_ai_generation_returns_validated_template(
    client, auth_headers, organization, app
) -> None:
    """A configured provider result is returned and the organization industry is used."""
    fake = FakeAIService()
    app.dependency_overrides[get_ai_service] = lambda: fake
    try:
        response = await client.post(
            "/api/v1/ai/generate-template",
            json={
                "target_department": "Finance",
                "scenario": "Urgent invoice from a known supplier",
                "channel": "email",
            },
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_ai_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["subject"] == "مرحباً {{first_name}}"
    assert payload["difficulty_level"] == 6
    assert payload["provider"] == "test"
    assert fake.calls[0]["organization_industry"] == "Technology"
    assert fake.calls[0]["target_department"] == "Finance"


async def test_viewer_cannot_generate(client, viewer_headers, organization) -> None:
    """Template generation is a write operation restricted to admin/manager."""
    response = await client.post(
        "/api/v1/ai/generate-template",
        json={"target_department": "Finance", "scenario": "Invoice"},
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_blank_scenario_is_rejected(client, auth_headers, organization) -> None:
    """Whitespace-only prompts fail validation before any provider call."""
    response = await client.post(
        "/api/v1/ai/generate-template",
        json={"target_department": "Finance", "scenario": "   "},
        headers=auth_headers,
    )
    assert response.status_code == 422
