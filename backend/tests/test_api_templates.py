"""API tests: email templates."""
from __future__ import annotations

import uuid

from app.models import Organization


async def test_list_builtin_templates(
    client, auth_headers, organization, builtin_templates
) -> None:
    """The thirteen built-in templates are listed."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-templates", headers=auth_headers
    )
    assert response.status_code == 200
    templates = response.json()
    assert len(templates) == 13
    assert all(template["is_built_in"] for template in templates)
    names = {template["name"] for template in templates}
    assert "Urgent Password Change" in names
    assert "Mandatory Software Update" in names


async def test_list_templates_search(
    client, auth_headers, organization, builtin_templates
) -> None:
    """Search filters templates by name."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-templates",
        params={"search": "invoice"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) >= 2


async def test_create_and_get_template(client, auth_headers, organization) -> None:
    """A custom template can be created and retrieved."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates",
        json={
            "name": "Custom Phish",
            "subject": "Hi {{first_name}}",
            "body_html": "<p>Hello {{first_name}}</p>",
            "difficulty_level": 6,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_built_in"] is False

    fetched = await client.get(
        f"/api/v1/organizations/{organization.id}/email-templates/{body['id']}",
        headers=auth_headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Custom Phish"


async def test_create_legacy_template_sanitizes_html(
    client, auth_headers, organization
) -> None:
    """Legacy body_html is sanitised before storage, not only at send time."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates",
        json={
            "name": "Unsafe legacy",
            "subject": "Hello",
            "body_html": (
                '<p>Hello</p><script>alert(1)</script>'
                '<a href="javascript:alert(1)">click</a>'
            ),
            "difficulty_level": 5,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    payload = response.json()
    assert "Hello" in payload["body_html"]
    assert "<script" not in payload["body_html"].lower()
    assert "javascript:" not in payload["body_html"].lower()
    assert payload["design_json"]["mode"] == "legacy"
    assert "javascript:" not in payload["design_json"]["legacy_html"].lower()


async def test_create_template_validation(client, auth_headers, organization) -> None:
    """Difficulty outside 1..10 is rejected."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates",
        json={"name": "Bad", "subject": "S", "body_html": "<p>x</p>", "difficulty_level": 99},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_update_template(client, auth_headers, organization, custom_template) -> None:
    """Templates can be updated."""
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/email-templates/{custom_template.id}",
        json={"subject": "Updated subject {{first_name}}"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["subject"].startswith("Updated subject")


async def test_delete_custom_template(client, auth_headers, organization, custom_template) -> None:
    """Custom templates can be deleted."""
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/email-templates/{custom_template.id}",
        headers=auth_headers,
    )
    assert response.status_code == 204


async def test_cannot_delete_builtin_template(
    client, auth_headers, organization, builtin_templates
) -> None:
    """Built-in templates are protected from deletion."""
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/email-templates/{builtin_templates[0].id}",
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_get_unknown_template(client, auth_headers, organization) -> None:
    """An unknown template id returns 404."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-templates/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_preview_template(client, auth_headers, organization, custom_template, employee) -> None:
    """Preview renders the template with real employee data."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates/{custom_template.id}/preview",
        json={"employee_id": str(employee.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "Jane" in body["subject"]
    assert "Jane" in body["html_content"]
    assert "/api/v1/track/" in body["html_content"]


async def test_preview_unknown_employee(
    client, auth_headers, organization, custom_template
) -> None:
    """Previewing for an unknown employee returns 404."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates/{custom_template.id}/preview",
        json={"employee_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_template_write_requires_privilege(
    client, viewer_headers, organization
) -> None:
    """A viewer cannot create templates."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates",
        json={"name": "Nope", "subject": "S", "body_html": "<p>x</p>"},
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_templates_require_auth(client, organization: Organization) -> None:
    """Template endpoints require authentication."""
    response = await client.get(f"/api/v1/organizations/{organization.id}/email-templates")
    assert response.status_code == 401
