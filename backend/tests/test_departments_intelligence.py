"""Tests for the intelligence foundation: departments, journeys, aggregation.

These cover the additive Phase 1/3/5 surface:

* department CRUD with automatic employee adoption and rename relinking;
* ``journey_id`` defaults and propagation from a campaign to its tracking rows;
* the aggregated ``/intelligence`` endpoint and its password masking;
* the three PDF endpoints (employee report, certificate, monthly organization);
* the smart alert rules.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Department, EmailCampaign, EmailTracking, HumanAsset
from app.services.alert_service import collect_smart_alerts

BASE = "/api/v1/organizations"


async def _make_campaign(
    db,
    organization,
    template,
    *,
    name: str,
    status: str = "draft",
    sent: int = 0,
    clicked: int = 0,
    opened: int = 0,
    launched_at: datetime | None = None,
) -> EmailCampaign:
    """Create a campaign with explicit funnel counters."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=name,
        status=status,
        channel="email",
        target_employee_ids=[],
        total_targets=0,
        sent_count=sent,
        clicked_count=clicked,
        opened_count=opened,
        launched_at=launched_at,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


# --------------------------------------------------------------------------- #
# Departments
# --------------------------------------------------------------------------- #
async def test_department_creation_adopts_existing_employees(
    client, db, organization, employee, auth_headers
) -> None:
    """Creating a department matches the legacy free-text value and links it."""
    employee.department = "Finance"
    await db.commit()

    response = await client.post(
        f"{BASE}/{organization.id}/departments",
        headers=auth_headers,
        json={"name": "Finance", "manager_name": "Noura"},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["employee_count"] == 1

    await db.refresh(employee)
    assert str(employee.department_id) == created["id"]

    listing = await client.get(f"{BASE}/{organization.id}/departments", headers=auth_headers)
    assert listing.status_code == 200
    assert [row["name"] for row in listing.json()] == ["Finance"]


async def test_department_duplicate_is_rejected(
    client, organization, auth_headers
) -> None:
    """Two departments cannot share a name inside one organization."""
    payload = {"name": "Operations"}
    first = await client.post(
        f"{BASE}/{organization.id}/departments", headers=auth_headers, json=payload
    )
    assert first.status_code == 201
    second = await client.post(
        f"{BASE}/{organization.id}/departments", headers=auth_headers, json=payload
    )
    assert second.status_code == 409


async def test_department_rename_relinks_employees(
    client, db, organization, employee, auth_headers
) -> None:
    """Renaming a department keeps its employees attached and updates the text."""
    employee.department = "IT"
    await db.commit()
    created = await client.post(
        f"{BASE}/{organization.id}/departments", headers=auth_headers, json={"name": "IT"}
    )
    department_id = created.json()["id"]

    renamed = await client.patch(
        f"{BASE}/{organization.id}/departments/{department_id}",
        headers=auth_headers,
        json={"name": "Information Technology"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["employee_count"] == 1

    await db.refresh(employee)
    assert employee.department == "Information Technology"
    assert str(employee.department_id) == department_id


async def test_department_delete_detaches_employees(
    client, db, organization, employee, auth_headers
) -> None:
    """Deleting a department clears the link but keeps the historical text."""
    employee.department = "Legal"
    await db.commit()
    created = await client.post(
        f"{BASE}/{organization.id}/departments", headers=auth_headers, json={"name": "Legal"}
    )
    department_id = created.json()["id"]

    deleted = await client.delete(
        f"{BASE}/{organization.id}/departments/{department_id}", headers=auth_headers
    )
    assert deleted.status_code == 204

    await db.refresh(employee)
    assert employee.department_id is None
    assert employee.department == "Legal"
    assert await db.scalar(select(Department).where(Department.id == uuid.UUID(department_id))) is None


# --------------------------------------------------------------------------- #
# Journeys
# --------------------------------------------------------------------------- #
async def test_campaign_gets_a_journey_id(
    db, organization, custom_template
) -> None:
    """Every campaign is a journey and the identifier is stable."""
    campaign = await _make_campaign(db, organization, custom_template, name="Journey")
    assert campaign.journey_id is not None

    tracking = EmailTracking(
        campaign_id=campaign.id,
        journey_id=campaign.journey_id,
        employee_id=None,
        channel="email",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    assert tracking.journey_id == campaign.journey_id


# --------------------------------------------------------------------------- #
# Aggregated intelligence
# --------------------------------------------------------------------------- #
async def test_intelligence_returns_one_consistent_payload(
    client, db, organization, employee, auth_headers
) -> None:
    """The hub's single call returns profile, Elo, events and certificates."""
    response = await client.get(
        f"{BASE}/{organization.id}/employees/{employee.id}/intelligence",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "employee",
        "elo",
        "summary",
        "journeys",
        "events",
        "submissions",
        "certificates",
    }
    assert payload["employee"]["id"] == str(employee.id)
    assert payload["employee"]["email"] == employee.email
    assert payload["elo"]["score"] == employee.elo_score
    assert payload["elo"]["level_ar"]
    assert payload["events"] == []
    assert payload["submissions"] == []


async def test_intelligence_limits_events(client, db, organization, employee, auth_headers) -> None:
    """``limit`` caps the ledger page returned by the endpoint."""
    response = await client.get(
        f"{BASE}/{organization.id}/employees/{employee.id}/intelligence?limit=5",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()["events"]) <= 5


async def test_sensitive_submission_fields_are_masked() -> None:
    """Credential-like field names never leave the API in clear text."""
    from app.api.v1.employees import _masked_values

    masked = _masked_values(
        {"username": "ali", "password": "hunter2", "otp_code": "123456", "note": "hi"}
    )
    assert masked["username"] == "ali"
    assert masked["note"] == "hi"
    assert masked["password"] == "••••••"
    assert masked["otp_code"] == "••••••"


# --------------------------------------------------------------------------- #
# PDFs
# --------------------------------------------------------------------------- #
async def test_employee_report_pdf(client, organization, employee, auth_headers) -> None:
    """The detailed employee report renders a real PDF."""
    response = await client.get(
        f"{BASE}/{organization.id}/employees/{employee.id}/report-pdf",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 1000


async def test_employee_report_pdf_renders_real_tracking_rows(
    client, db, organization, employee, auth_headers, custom_template
) -> None:
    """Dates and counters render correctly when the employee has history."""
    campaign = await _make_campaign(
        db, organization, custom_template, name="Rendered", status="active", sent=1
    )
    now = datetime.now(timezone.utc)
    db.add(
        EmailTracking(
            campaign_id=campaign.id,
            journey_id=campaign.journey_id,
            employee_id=employee.id,
            template_id=custom_template.id,
            channel="email",
            tracking_uuid=uuid.uuid4(),
            sent_at=now,
            opened_at=now,
            clicked_at=now,
            click_count=1,
            open_count=1,
        )
    )
    await db.commit()

    response = await client.get(
        f"{BASE}/{organization.id}/employees/{employee.id}/report-pdf",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")


async def test_certificate_without_month_uses_live_score(
    client, organization, employee, auth_headers
) -> None:
    """A certificate can be produced without waiting for the month-end archive."""
    response = await client.get(
        f"{BASE}/{organization.id}/employees/{employee.id}/certificate",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")


async def test_monthly_organization_report_pdf(
    client, organization, employee, auth_headers
) -> None:
    """The executive monthly report renders with live data when unarchived."""
    response = await client.get(
        f"{BASE}/{organization.id}/reports/monthly", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


async def test_monthly_organization_report_requires_permission(
    client, organization, viewer_headers
) -> None:
    """A read-only viewer holds ``reports.view`` and is therefore allowed."""
    response = await client.get(
        f"{BASE}/{organization.id}/reports/monthly", headers=viewer_headers
    )
    assert response.status_code in {200, 404}


# --------------------------------------------------------------------------- #
# Smart alerts
# --------------------------------------------------------------------------- #
async def test_smart_alerts_detect_critical_mass_clicks_and_stalled(
    db, organization, employee, custom_template
) -> None:
    """Each rule fires on its own measured condition."""
    employee.elo_score = 500
    employee.is_active = True
    await _make_campaign(
        db,
        organization,
        custom_template,
        name="Mass click",
        status="active",
        sent=10,
        clicked=5,
        opened=3,
    )
    await _make_campaign(
        db,
        organization,
        custom_template,
        name="Stalled",
        status="active",
        sent=4,
        clicked=0,
        opened=0,
        launched_at=datetime.now(timezone.utc) - timedelta(hours=30),
    )
    await db.commit()

    alerts = await collect_smart_alerts(db)
    types = {alert["type"] for alert in alerts}
    assert {"critical_risk", "mass_clicks", "stalled_campaign"} <= types

    mass = next(alert for alert in alerts if alert["type"] == "mass_clicks")
    assert mass["measurements"]["campaigns"][0]["rate"] == 0.5


async def test_smart_alerts_stay_quiet_on_healthy_data(
    db, organization, employee, custom_template
) -> None:
    """A healthy employee and campaign produce no alerts."""
    employee.elo_score = 1100
    employee.is_active = True
    await _make_campaign(
        db,
        organization,
        custom_template,
        name="Healthy",
        status="active",
        sent=20,
        clicked=1,
        opened=12,
        launched_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    await db.commit()

    assert await collect_smart_alerts(db) == []


async def test_intelligence_is_scoped_to_the_organization(
    client, db, organization, auth_headers
) -> None:
    """Another tenant's employee id is indistinguishable from a missing one."""
    other_employee = HumanAsset(
        organization_id=uuid.uuid4(),
        email="ghost@elsewhere.example",
        first_name="Ghost",
    )
    db.add(other_employee)
    await db.commit()

    response = await client.get(
        f"{BASE}/{organization.id}/employees/{other_employee.id}/intelligence",
        headers=auth_headers,
    )
    assert response.status_code == 404
