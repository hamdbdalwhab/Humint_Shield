"""API tests: LMS (dashboard, training library, assignments, report inbox)."""
from __future__ import annotations

import uuid

from app.models import Organization


async def test_dashboard_empty(client, auth_headers, organization) -> None:
    """A fresh organization returns a zeroed dashboard."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/dashboard", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_employees"] == 0
    assert body["total_campaigns"] == 0
    assert body["open_rate"] == 0.0


async def test_dashboard_with_data(
    client, auth_headers, organization, employees, builtin_templates
) -> None:
    """The dashboard reflects employees and templates."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/dashboard", headers=auth_headers
    )
    body = response.json()
    assert body["total_employees"] == 5
    assert body["active_employees"] == 4
    assert body["total_templates"] == 18


async def test_training_library_list(client, auth_headers, organization, training_modules) -> None:
    """The seeded training catalogue is listed."""
    assert training_modules == 4
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/training-modules", headers=auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 4


async def test_create_training_module(client, auth_headers, organization) -> None:
    """A training module can be added."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/training-modules",
        json={"title": "New Module", "summary": "Summary", "duration_minutes": 15},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["title"] == "New Module"


async def test_assignments_flow(client, auth_headers, organization, employees, training_modules) -> None:
    """Assignments can be created, listed and completed."""
    modules = (
        await client.get(
            f"/api/v1/organizations/{organization.id}/training-modules", headers=auth_headers
        )
    ).json()
    module_id = modules[0]["id"]

    created = await client.post(
        f"/api/v1/organizations/{organization.id}/assignments",
        json={"module_id": module_id, "employee_id": str(employees[0].id)},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assignment_id = created.json()["id"]
    assert created.json()["module_title"] == modules[0]["title"]

    listing = await client.get(
        f"/api/v1/organizations/{organization.id}/assignments", headers=auth_headers
    )
    assert len(listing.json()) == 1

    completed = await client.post(
        f"/api/v1/organizations/{organization.id}/assignments/{assignment_id}/complete",
        headers=auth_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None


async def test_create_assignment_unknown_module(client, auth_headers, organization) -> None:
    """An unknown module returns 404."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/assignments",
        json={"module_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_complete_unknown_assignment(client, auth_headers, organization) -> None:
    """Completing an unknown assignment returns 404."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/assignments/{uuid.uuid4()}/complete",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_report_inbox_flow(client, auth_headers, organization, employee, db) -> None:
    """Reports can be filed, listed and triaged and feed the employee counter."""
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/reports",
        json={
            "employee_id": str(employee.id),
            "reported_email_subject": "Suspicious invoice",
            "reported_sender": "billing@evil.example",
            "description": "Unexpected invoice",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    report_id = created.json()["id"]
    assert created.json()["status"] == "new"

    listing = await client.get(
        f"/api/v1/organizations/{organization.id}/reports", headers=auth_headers
    )
    assert len(listing.json()) == 1
    assert len(
        (
            await client.get(
                f"/api/v1/organizations/{organization.id}/reports",
                params={"status": "new"},
                headers=auth_headers,
            )
        ).json()
    ) == 1

    await db.refresh(employee)
    assert employee.total_reports == 1

    updated = await client.put(
        f"/api/v1/organizations/{organization.id}/reports/{report_id}",
        json={"status": "resolved", "triage_notes": "Confirmed phishing, blocked sender"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"


async def test_report_with_foreign_employee_is_anonymised(
    client, auth_headers, organization, db
) -> None:
    """A report referencing a foreign employee drops the employee link."""
    from app.models import HumanAsset

    other = Organization(name="Other", domain="other-reports.example")
    db.add(other)
    await db.flush()
    foreign = HumanAsset(
        organization_id=other.id, email="f@other-reports.example", first_name="F", last_name="L"
    )
    db.add(foreign)
    await db.commit()

    response = await client.post(
        f"/api/v1/organizations/{organization.id}/reports",
        json={"employee_id": str(foreign.id), "reported_email_subject": "x"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["employee_id"] is None


async def test_update_unknown_report(client, auth_headers, organization) -> None:
    """Triaging an unknown report returns 404."""
    response = await client.put(
        f"/api/v1/organizations/{organization.id}/reports/{uuid.uuid4()}",
        json={"status": "resolved"},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_lms_requires_auth(client, organization) -> None:
    """LMS endpoints require authentication."""
    assert (await client.get(f"/api/v1/organizations/{organization.id}/dashboard")).status_code == 401
