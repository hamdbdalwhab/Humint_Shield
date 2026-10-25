"""API tests: campaigns."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailTracking, HumanAsset, Organization


@pytest.fixture
def captured_emails(monkeypatch):
    """Patch the launcher's Brevo transport with an in-memory recorder."""
    from app.services import campaign_launcher as launcher_module

    sent: list[dict] = []

    class _Recorder:
        async def send_training_email(
            self, to_email, to_name, subject, html_content, correlation_id=None
        ):  # noqa: ANN001
            sent.append({"to": to_email, "subject": subject, "html": html_content})
            return {"success": True, "message_id": f"<api-{len(sent)}@brevo>", "error": None}

    original = launcher_module.CampaignLauncher.__init__

    def _patched(self, email_service=None, personalizer=None):  # noqa: ANN001
        original(self, email_service=email_service or _Recorder(), personalizer=personalizer)

    monkeypatch.setattr(launcher_module.CampaignLauncher, "__init__", _patched)
    return sent


async def test_create_campaign(client, auth_headers, organization, custom_template, employees) -> None:
    """A campaign can be created as a draft."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Q1 Simulation",
            "template_id": str(custom_template.id),
            "difficulty_level": 5,
            "target_employee_ids": [str(e.id) for e in employees[:3]],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["total_targets"] == 3
    assert len(body["target_employee_ids"]) == 3


async def test_create_campaign_unknown_template(client, auth_headers, organization, employees) -> None:
    """An unknown template returns 404."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Bad",
            "template_id": str(uuid.uuid4()),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_create_campaign_no_valid_targets(
    client, auth_headers, organization, custom_template
) -> None:
    """All-foreign targets are rejected."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Bad",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(uuid.uuid4())],
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_list_and_get_campaign(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """Campaigns can be listed and fetched."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "List Me",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]

    listing = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns", headers=auth_headers
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    filtered = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        params={"status": "draft"},
        headers=auth_headers,
    )
    assert len(filtered.json()) == 1

    single = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}",
        headers=auth_headers,
    )
    assert single.status_code == 200
    assert single.json()["name"] == "List Me"


async def test_update_draft_campaign(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """A draft campaign can be edited."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Draft",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}",
        json={"name": "Renamed", "target_employee_ids": [str(e.id) for e in employees[:2]]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["total_targets"] == 2


async def test_delete_draft_campaign(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """A draft campaign can be deleted."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Delete Me",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204


async def test_full_campaign_lifecycle(
    client, auth_headers, organization, custom_template, employees, captured_emails, db: AsyncSession
) -> None:
    """Create -> launch -> track -> results -> export, end to end."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Lifecycle",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(e.id) for e in employees[:3]],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]

    launch = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/launch",
        headers=auth_headers,
    )
    assert launch.status_code == 200
    launch_body = launch.json()
    assert launch_body["total"] == 3
    assert launch_body["sent"] == 3
    assert launch_body["failed"] == 0
    assert len(captured_emails) == 3
    # Personalised with the real first name.
    assert any(employees[0].first_name in message["subject"] for message in captured_emails)
    # Tracking pixel + click URLs present.
    assert all("/api/v1/track/open/" in message["html"] for message in captured_emails)

    rows = (
        await db.execute(
            select(EmailTracking)
            .where(EmailTracking.campaign_id == uuid.UUID(campaign_id))
            .order_by(EmailTracking.created_at.asc())
        )
    ).scalars().all()
    assert len(rows) == 3

    # Open the first, click the second, complete the second.
    opened = await client.get(f"/api/v1/track/open/{rows[0].tracking_uuid}")
    assert opened.status_code == 200
    assert opened.headers["content-type"] == "image/gif"

    clicked = await client.get(
        f"/api/v1/track/click/{rows[1].tracking_uuid}",
        params={"url": "https://portal.example.com/verify"},
        follow_redirects=False,
    )
    assert clicked.status_code == 302
    assert f"/phish/{rows[1].tracking_uuid}" in clicked.headers["location"]

    completed = await client.post(f"/api/v1/track/complete/{rows[1].tracking_uuid}")
    assert completed.status_code == 200
    assert completed.json()["success"] is True

    results = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/results",
        headers=auth_headers,
    )
    assert results.status_code == 200
    body = results.json()
    assert body["stats"]["sent"] == 3
    assert body["stats"]["opened"] == 2
    assert body["stats"]["clicked"] == 1
    assert body["stats"]["completed"] == 1
    assert len(body["employees"]) == 3

    export = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/export",
        headers=auth_headers,
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "attachment" in export.headers["content-disposition"]
    csv_text = export.text
    assert "employee_id,name,email,phone,channel,department,status" in csv_text
    assert "delivery_status" in csv_text
    assert "provider_message_id" in csv_text
    assert "submitted_at" in csv_text
    assert "password_length" in csv_text
    assert employees[0].email in csv_text


async def test_relaunch_rejected(
    client, auth_headers, organization, custom_template, employees, captured_emails
) -> None:
    """A completed campaign cannot be launched again."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Once",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]
    first = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/launch",
        headers=auth_headers,
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/launch",
        headers=auth_headers,
    )
    assert second.status_code == 400


async def test_campaign_results_after_launch(
    client, auth_headers, organization, custom_template, employees, captured_emails
) -> None:
    """Results for a campaign with no engagement show zeroed rates."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Quiet",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=auth_headers,
    )
    campaign_id = created.json()["id"]
    await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/launch",
        headers=auth_headers,
    )
    results = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/results",
        headers=auth_headers,
    )
    body = results.json()
    assert body["stats"]["open_rate"] == 0.0
    assert body["employees"][0]["status"] == "sent"


async def test_campaign_requires_privilege(
    client, viewer_headers, organization, custom_template, employees
) -> None:
    """A viewer cannot create campaigns."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Nope",
            "template_id": str(custom_template.id),
            "target_employee_ids": [str(employees[0].id)],
        },
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_campaign_unknown_id(client, auth_headers, organization) -> None:
    """An unknown campaign returns 404."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_campaign_not_found_launch(client, auth_headers, organization) -> None:
    """Launching an unknown campaign returns 404."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{uuid.uuid4()}/launch",
        headers=auth_headers,
    )
    assert response.status_code == 404
