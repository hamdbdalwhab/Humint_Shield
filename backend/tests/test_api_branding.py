"""API tests for organization branding and visual template persistence."""
from __future__ import annotations

import io

from PIL import Image

from app.schemas.email_design import EmailDesign, TextBlock
from app.services.email_design import BrandingContext, default_design


def _design_payload(color: str = "#123456") -> dict:
    """Return a JSON-safe starter design for API tests."""
    return default_design(
        BrandingContext(
            company_name="Acme Test Corporation",
            primary_color=color,
            support_email="support@acmetest.example",
        )
    ).model_dump(mode="json")


def _png_bytes() -> bytes:
    """Create a small valid PNG without external fixture files."""
    buffer = io.BytesIO()
    Image.new("RGB", (120, 60), "#0F6CBD").save(buffer, format="PNG")
    return buffer.getvalue()


async def test_get_and_update_branding(client, auth_headers, organization) -> None:
    """Branding is readable and writable by an administrator."""
    url = f"/api/v1/organizations/{organization.id}/branding"
    initial = await client.get(url, headers=auth_headers)
    assert initial.status_code == 200
    assert initial.json()["company_name"] == "Acme Test Corporation"
    assert initial.json()["primary_color"] == "#0F6CBD"

    updated = await client.put(
        url,
        headers=auth_headers,
        json={
            "company_name": "Acme Shield",
            "primary_color": "#12ab34",
            "support_email": "help@acmetest.example",
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["company_name"] == "Acme Shield"
    assert payload["primary_color"] == "#12AB34"
    assert payload["support_email"] == "help@acmetest.example"


async def test_branding_update_requires_manager_role(
    client, viewer_headers, organization
) -> None:
    """A viewer cannot change organization branding."""
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/branding",
        headers=viewer_headers,
        json={"company_name": "Nope"},
    )
    assert response.status_code == 403


async def test_logo_upload_is_normalised_and_publicly_served(
    client, auth_headers, organization
) -> None:
    """A raster logo is re-encoded to PNG and served without auth."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/branding/logo",
        headers=auth_headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["has_logo"] is True
    assert payload["logo_url"]
    assert "/logo" in payload["logo_url"]

    public = await client.get(
        f"/api/v1/public/branding/{organization.id}/logo"
    )
    assert public.status_code == 200
    assert public.headers["content-type"] == "image/png"
    assert public.content.startswith(b"\x89PNG")

    removed = await client.delete(
        f"/api/v1/organizations/{organization.id}/branding/logo",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["has_logo"] is False


async def test_logo_rejects_non_image(client, auth_headers, organization) -> None:
    """An SVG or arbitrary payload is not accepted as a logo."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/branding/logo",
        headers=auth_headers,
        files={"file": ("logo.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
    )
    assert response.status_code == 400


async def test_create_template_compiles_design_and_branding(
    client, auth_headers, organization
) -> None:
    """design_json is the source of truth and is compiled server-side."""
    await client.put(
        f"/api/v1/organizations/{organization.id}/branding",
        headers=auth_headers,
        json={"company_name": "Brand Co", "primary_color": "#123456"},
    )
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates",
        headers=auth_headers,
        json={
            "name": "Visual template",
            "subject": "Hello {{first_name}}",
            "design_json": _design_payload("#123456"),
            "channel": "email",
            "difficulty_level": 5,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["design_json"]["mode"] == "blocks"
    assert "#123456" in payload["body_html"]
    assert "Brand Co" in payload["body_html"]
    assert "{{first_name}}" in payload["body_html"]


async def test_design_endpoint_wraps_builtin_template(
    client, auth_headers, organization, builtin_templates
) -> None:
    """Every built-in opens in legacy mode without losing its original HTML."""
    template = builtin_templates[0]
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-templates/{template.id}/design",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "legacy"
    assert payload["legacy_html"] == template.body_html


async def test_update_template_with_design_recompiles_html(
    client, auth_headers, organization, custom_template
) -> None:
    """Updating design_json replaces body_html and removes XSS payloads."""
    design = EmailDesign(
        blocks=[
            TextBlock(
                id="block-1",
                content='<p onclick="alert(1)">Visual update</p><script>alert(1)</script>',
            )
        ]
    )
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/email-templates/{custom_template.id}",
        headers=auth_headers,
        json={"design_json": design.model_dump(mode="json")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "Visual update" in payload["body_html"]
    assert "<script" not in payload["body_html"].lower()
    assert "onclick" not in payload["body_html"].lower()
    assert payload["design_json"]["blocks"][0]["content"].startswith("<p onclick")


async def test_test_send_uses_dummy_employee_and_dry_run(
    client, auth_headers, organization
) -> None:
    """The test-send endpoint renders merge tags and never creates tracking."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates/test-send",
        headers=auth_headers,
        json={
            "subject": "Test {{first_name}}",
            "design_json": _design_payload(),
            "channel": "email",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["to_email"] == "tester@acmetest.example"
    assert payload["preview_html"]
    assert "سارة" in payload["preview_html"]
    assert "tester@acmetest.example" in payload["preview_html"]
