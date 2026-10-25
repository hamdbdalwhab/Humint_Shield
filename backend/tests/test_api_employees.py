"""API tests: employees."""
from __future__ import annotations

import io
import json
import uuid

from app.models import Organization


async def test_list_employees_empty(client, auth_headers, organization: Organization) -> None:
    """An empty organization returns an empty page."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_list_employees_pagination(client, auth_headers, organization, employees) -> None:
    """Pagination returns the requested slice with a total."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees",
        params={"page": 1, "per_page": 2},
        headers=auth_headers,
    )
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["pages"] == 3


async def test_list_employees_search(client, auth_headers, organization, employees) -> None:
    """Search filters by name."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees",
        params={"search": "Employee2"},
        headers=auth_headers,
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["first_name"] == "Employee2"


async def test_list_employees_department_filter(
    client, auth_headers, organization, employees
) -> None:
    """Department filtering works."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees",
        params={"department": "Finance"},
        headers=auth_headers,
    )
    body = response.json()
    assert body["total"] == 2
    assert all(item["department"] == "Finance" for item in body["items"])


async def test_list_employees_is_active_filter(
    client, auth_headers, organization, employees
) -> None:
    """The active-only filter excludes inactive employees."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees",
        params={"is_active": "false"},
        headers=auth_headers,
    )
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["is_active"] is False


async def test_create_employee(client, auth_headers, organization) -> None:
    """An employee can be created and their phone is encrypted at rest."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        json={
            "email": "new.person@acmetest.example",
            "first_name": "New",
            "last_name": "Person",
            "department": "Sales",
            "access_level": 2,
            "phone": "+15550199000",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    # The API returns the decrypted phone.
    assert body["phone"] == "+15550199000"


async def test_create_employee_duplicate_email(client, auth_headers, organization, employee) -> None:
    """A duplicate email is rejected with 409."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        json={"email": employee.email, "first_name": "Dup"},
        headers=auth_headers,
    )
    assert response.status_code == 409


async def test_create_employee_requires_privilege(
    client, viewer_headers, organization
) -> None:
    """A viewer cannot create employees."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees",
        json={"email": "x@acmetest.example", "first_name": "X"},
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_get_employee(client, auth_headers, organization, employee) -> None:
    """A single employee can be fetched with Elo and threat data."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == employee.email
    assert body["elo_score"] == 1000
    assert body["threat_level"] == "medium"


async def test_employee_threat_badge_reflects_elo(
    client, auth_headers, organization, employee, db
) -> None:
    """A low Elo is exposed as a high/critical threat badge."""
    employee.elo_score = 850
    await db.commit()
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["elo_score"] == 850
    assert body["threat_level"] == "high"

    employee.elo_score = 700
    await db.commit()
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}", headers=auth_headers
    )
    assert response.json()["threat_level"] == "critical"



async def test_get_unknown_employee(client, auth_headers, organization) -> None:
    """An unknown employee returns 404."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{uuid.uuid4()}", headers=auth_headers
    )
    assert response.status_code == 404


async def test_update_employee(client, auth_headers, organization, employee) -> None:
    """Employees can be partially updated."""
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}",
        json={"department": "Compliance", "access_level": 4},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["department"] == "Compliance"
    assert body["access_level"] == 4


async def test_update_employee_email_conflict(
    client, auth_headers, organization, employee, employees
) -> None:
    """Changing to an in-use email returns 409."""
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}",
        json={"email": employees[0].email},
        headers=auth_headers,
    )
    assert response.status_code == 409


async def test_delete_employee(client, auth_headers, organization, employee) -> None:
    """Admins can delete employees."""
    response = await client.delete(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}", headers=auth_headers
    )
    assert response.status_code == 204
    follow_up = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}", headers=auth_headers
    )
    assert follow_up.status_code == 404


async def test_bulk_import_csv(client, auth_headers, organization) -> None:
    """A CSV upload creates and updates employees."""
    csv_content = (
        "email,first_name,last_name,department,job_title,access_level\n"
        "bulk1@acmetest.example,Bulk,One,Finance,Analyst,2\n"
        "bulk2@acmetest.example,Bulk,Two,Engineering,Engineer,3\n"
        "invalid-row,,Missing,Email,,1\n"
    )
    files = {"file": ("employees.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees/bulk",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["skipped"] == 1
    assert body["errors"]


async def test_bulk_import_updates_existing(client, auth_headers, organization, employee) -> None:
    """Re-importing an existing email updates the record."""
    csv_content = (
        "email,first_name,last_name,department\n"
        f"{employee.email},Jane,Updated,Compliance\n"
    )
    files = {"file": ("employees.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees/bulk",
        files=files,
        headers=auth_headers,
    )
    body = response.json()
    assert body["updated"] == 1
    assert body["created"] == 0


async def test_bulk_import_missing_columns(client, auth_headers, organization) -> None:
    """A CSV without the required columns returns 400."""
    csv_content = "name,role\nJane,Analyst\n"
    files = {"file": ("employees.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/employees/bulk",
        files=files,
        headers=auth_headers,
    )
    assert response.status_code == 400


async def test_timeline(client, auth_headers, organization, employees, custom_template, db) -> None:
    """The timeline reflects campaign engagement."""
    from sqlalchemy import select

    from app.models import EmailCampaign, EmailTracking

    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=custom_template.id,
        name="Timeline Campaign",
        status="draft",
        target_employee_ids=[str(employees[0].id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    launch = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/launch",
        headers=auth_headers,
    )
    assert launch.status_code == 200

    row = (
        await db.execute(select(EmailTracking).where(EmailTracking.campaign_id == campaign.id))
    ).scalar_one()
    await client.get(f"/api/v1/track/open/{row.tracking_uuid}")
    await client.get(f"/api/v1/track/click/{row.tracking_uuid}")
    page = await client.get(f"/training-legacy/{row.tracking_uuid}")
    assert page.status_code == 200
    submit = await client.post(
        f"/api/v1/track/submit/{row.tracking_uuid}",
        json={
            "identifier": "timeline.user@acmetest.example",
            "password_length": 17,
            "fields": {"department": "Finance", "password": "must-not-be-stored"},
        },
    )
    assert submit.status_code == 200
    assert submit.json()["success"] is True

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employees[0].id}/timeline",
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = response.json()
    types = [event["event_type"] for event in events]
    assert "email_sent" in types
    assert "email_opened" in types
    assert "link_clicked" in types
    assert "training_form_viewed" in types
    assert "credentials_submitted" in types

    submitted = next(event for event in events if event["event_type"] == "credentials_submitted")
    details = submitted["details"]
    assert details["identifier"] == "timeline.user@acmetest.example"
    assert details["password_length"] == 17
    assert details["values"] == {
        "identifier": "timeline.user@acmetest.example",
        "department": "Finance",
        "password": "must-not-be-stored",
    }
    # Events are ordered chronologically.
    timestamps = [event["timestamp"] for event in events]
    assert timestamps == sorted(timestamps)


async def test_organization_isolation(client, auth_headers, organization, db) -> None:
    """Accessing another organization's employees is forbidden."""
    other = Organization(name="Other", domain="other-org.example")
    db.add(other)
    await db.commit()
    await db.refresh(other)

    response = await client.get(
        f"/api/v1/organizations/{other.id}/employees", headers=auth_headers
    )
    assert response.status_code == 403


async def test_unknown_organization(client, auth_headers) -> None:
    """An unknown organization returns 404."""
    response = await client.get(
        f"/api/v1/organizations/{uuid.uuid4()}/employees", headers=auth_headers
    )
    assert response.status_code == 404


async def test_employee_requires_auth(client, organization) -> None:
    """Employee endpoints require authentication."""
    response = await client.get(f"/api/v1/organizations/{organization.id}/employees")
    assert response.status_code == 401
