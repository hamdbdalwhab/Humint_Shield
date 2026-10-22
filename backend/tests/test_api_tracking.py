"""API tests: tracking endpoints and the training page."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTracking, Organization, PhishingReport
from app.services.template_service import TRANSPARENT_GIF


async def _seed_tracking(
    db: AsyncSession, organization: Organization, employee, template
) -> EmailTracking:
    """Create a campaign and tracking row directly."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Tracking API Campaign",
        status="completed",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
    )
    db.add(campaign)
    await db.flush()
    from datetime import datetime, timezone

    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        email_template_id=template.id,
        tracking_uuid=uuid.uuid4(),
        sent_at=datetime.now(timezone.utc),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


async def test_open_pixel_returns_gif(client, db, organization, employee, custom_template) -> None:
    """The open endpoint returns the transparent GIF with no-cache headers."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.get(
        f"/api/v1/track/open/{tracking.tracking_uuid}",
        headers={"User-Agent": "TestMailClient/9"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"
    assert response.content == TRANSPARENT_GIF
    assert response.content.startswith(b"GIF89a")
    assert "no-store" in response.headers["cache-control"]

    await db.refresh(tracking)
    assert tracking.opened_at is not None
    assert tracking.last_user_agent == "TestMailClient/9"


async def test_open_pixel_unknown_uuid_is_quiet(client) -> None:
    """An unknown UUID still returns a GIF (no information disclosure)."""
    response = await client.get(f"/api/v1/track/open/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.content == TRANSPARENT_GIF


async def test_open_pixel_invalid_uuid_is_quiet(client) -> None:
    """A malformed UUID also returns a GIF."""
    response = await client.get("/api/v1/track/open/not-a-uuid")
    assert response.status_code == 200
    assert response.content == TRANSPARENT_GIF


async def test_click_redirects_to_training_page(
    client, db, organization, employee, custom_template
) -> None:
    """A click is recorded and the recipient is redirected to the training page."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.get(
        f"/api/v1/track/click/{tracking.tracking_uuid}",
        params={"url": "https://portal.example.com/verify"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(f"/training/{tracking.tracking_uuid}")

    await db.refresh(tracking)
    assert tracking.clicked_at is not None
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.clicked_count == 1


async def test_click_unknown_uuid_still_redirects(client) -> None:
    """An unknown click UUID redirects without error."""
    identifier = uuid.uuid4()
    response = await client.get(
        f"/api/v1/track/click/{identifier}", follow_redirects=False
    )
    assert response.status_code == 302
    assert str(identifier) in response.headers["location"]


async def test_complete_endpoint(client, db, organization, employee, custom_template) -> None:
    """Completing the training records the timestamp."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.post(f"/api/v1/track/complete/{tracking.tracking_uuid}")
    assert response.status_code == 200
    assert response.json()["success"] is True

    await db.refresh(tracking)
    assert tracking.completed_training_at is not None
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.completed_count == 1


async def test_complete_unknown_uuid(client) -> None:
    """Completing with an unknown UUID reports failure gracefully."""
    response = await client.post(f"/api/v1/track/complete/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["success"] is False


async def test_complete_invalid_uuid(client) -> None:
    """A malformed completion UUID is rejected gracefully."""
    response = await client.post("/api/v1/track/complete/not-a-uuid")
    assert response.status_code == 200
    assert response.json()["success"] is False


async def test_training_page_renders_the_simulated_form(
    client, db, organization, employee, custom_template
) -> None:
    """A fresh recipient sees the simulated sign-in form, not the reveal."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.get(f"/training/{tracking.tracking_uuid}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert "Verify your identity" in html
    assert 'id="identifier"' in html
    assert 'id="password"' in html
    assert f"/api/v1/track/submit/{tracking.tracking_uuid}" in html
    # The reveal must not leak before the recipient interacts.
    assert "This was a training exercise" not in html
    assert "Red flags you may have missed" not in html

    await db.refresh(tracking)
    row = tracking
    assert row.form_viewed_at is not None


async def test_training_page_unknown_uuid(client) -> None:
    """An unknown training UUID returns the graceful fallback page."""
    response = await client.get(f"/training/{uuid.uuid4()}")
    assert response.status_code == 200
    assert "not recognised" in response.text


async def test_training_page_invalid_uuid(client) -> None:
    """A malformed training UUID returns the fallback page."""
    response = await client.get("/training/not-a-uuid")
    assert response.status_code == 200
    assert "not recognised" in response.text


async def test_training_page_after_completion(
    client, db, organization, employee, custom_template
) -> None:
    """The page reflects an already-completed simulation."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.post(f"/api/v1/track/complete/{tracking.tracking_uuid}")
    response = await client.get(f"/training/{tracking.tracking_uuid}")
    assert "already completed" in response.text


async def test_double_open_increments_once_per_open(
    client, db, organization, employee, custom_template
) -> None:
    """Repeated pixel loads increment ``open_count`` but not the campaign total."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    for _ in range(3):
        await client.get(f"/api/v1/track/open/{tracking.tracking_uuid}")
    await db.refresh(tracking)
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert tracking.open_count == 3
    assert campaign.opened_count == 1


async def test_tracking_routes_need_no_auth(client, db, organization, employee, custom_template) -> None:
    """Tracking works without an Authorization header."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    assert (await client.get(f"/api/v1/track/open/{tracking.tracking_uuid}")).status_code == 200
    assert (await client.post(f"/api/v1/track/complete/{tracking.tracking_uuid}")).status_code == 200


async def test_click_implies_open(client, db, organization, employee, custom_template) -> None:
    """A click without a prior open still marks the email as opened."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.get(f"/api/v1/track/click/{tracking.tracking_uuid}", follow_redirects=False)
    await db.refresh(tracking)
    assert tracking.opened_at is not None
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.opened_count == 1


async def test_tracking_persists_across_sessions(
    client, db, organization, employee, custom_template
) -> None:
    """Tracking writes are committed and visible to a fresh query."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    tracking_uid = tracking.tracking_uuid
    await client.get(f"/api/v1/track/open/{tracking_uid}")
    db.expire_all()  # the API committed in a separate session
    row = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.tracking_uuid == tracking_uid)
        )
    ).scalar_one()
    assert row.opened_at is not None


# --------------------------------------------------------------------------- #
# Simulated credential form
# --------------------------------------------------------------------------- #
async def test_submit_records_the_interaction_without_the_password(
    client, db, organization, employee, custom_template
) -> None:
    """The submission is stored, but the password never reaches the database."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={
            "identifier": "jane.doe@acmetest.example",
            "password_length": 11,
            "fields": {"department": "Finance", "password": "SuperSecret1"},
        },
        headers={"User-Agent": "TestBrowser/1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["first_time"] is True

    await db.refresh(tracking)
    row = tracking
    assert row.form_submitted_at is not None
    assert row.submission_count == 1
    assert row.submitted_identifier == "jane.doe@acmetest.example"
    assert row.password_length == 11
    # Non-secret fields are kept; password-like keys are dropped server-side.
    assert row.submitted_fields == {"department": "Finance"}
    assert "SuperSecret1" not in str(row.submitted_fields)


async def test_submit_implies_open_and_click(
    client, db, organization, employee, custom_template
) -> None:
    """Submitting the form marks the message as opened and clicked."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={"identifier": "jane.doe@acmetest.example", "password_length": 8, "fields": {}},
    )
    await db.refresh(tracking)
    row = tracking
    assert row.opened_at is not None
    assert row.clicked_at is not None
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.opened_count == 1
    assert campaign.clicked_count == 1


async def test_submit_is_counted_once_against_the_employee(
    client, db, organization, employee, custom_template
) -> None:
    """Repeat submissions increment the row counter but penalise once."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    first = await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={"identifier": "a@acmetest.example", "password_length": 4, "fields": {}},
    )
    second = await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={"identifier": "b@acmetest.example", "password_length": 9, "fields": {}},
    )
    assert first.json()["first_time"] is True
    assert second.json()["first_time"] is False

    await db.refresh(tracking)
    row = tracking
    assert row.submission_count == 2
    assert row.submitted_identifier == "b@acmetest.example"
    await db.refresh(employee)
    assert employee.total_credential_submissions == 1


async def test_submit_drops_the_employee_into_critical_risk(
    client, db, organization, employee, custom_template
) -> None:
    """A credential submission is the strongest negative signal."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={"identifier": "jane.doe@acmetest.example", "password_length": 10, "fields": {}},
    )
    await db.refresh(employee)
    assert float(employee.immunity_score) == 0.0
    assert employee.behavioral_category == "critical_risk"
    assert employee.under_enhanced_monitoring is True


async def test_submit_unknown_uuid_is_graceful(client) -> None:
    """An unknown UUID returns ``success=False`` with a 200 status."""
    response = await client.post(
        f"/api/v1/track/submit/{uuid.uuid4()}",
        json={"identifier": "x@y.example", "password_length": 3, "fields": {}},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


async def test_submit_invalid_uuid_is_graceful(client) -> None:
    """A malformed UUID is rejected without raising."""
    response = await client.post(
        "/api/v1/track/submit/not-a-uuid",
        json={"identifier": "x@y.example", "password_length": 3, "fields": {}},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


async def test_training_page_reveals_after_submission(
    client, db, organization, employee, custom_template
) -> None:
    """After the form is used the page discloses the simulation."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={
            "identifier": "jane.doe@acmetest.example",
            "password": "s3cret",
            "password_length": 6,
            "fields": {"password": "s3cret"},
        },
    )
    response = await client.get(f"/training/{tracking.tracking_uuid}")
    html = response.text
    assert "This was a training exercise" in html
    assert "Red flags you may have missed" in html
    assert "stored encrypted" in html
    # The page confirms the capture without echoing the secret back.
    assert "s3cret" not in html
    assert "6 characters" in html
    assert "complete-btn" in html
    assert "Jane" in html
    assert "Verify your identity" not in html


async def test_report_endpoint_creates_inbox_entry(
    client, db, organization, employee, custom_template
) -> None:
    """Reporting the simulation files a report and counts as a good behaviour."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    response = await client.post(f"/api/v1/track/report/{tracking.tracking_uuid}")
    assert response.status_code == 200
    assert response.json()["success"] is True

    await db.refresh(tracking)
    row = tracking
    assert row.reported_at is not None

    reports = (
        await db.execute(
            select(PhishingReport).where(PhishingReport.employee_id == employee.id)
        )
    ).scalars().all()
    assert len(reports) == 1
    assert reports[0].is_training_simulation is True

    await db.refresh(employee)
    assert employee.total_reports == 1
    # Reporting without clicking raises the score above the baseline.
    assert float(employee.immunity_score) > 50.0

    again = await client.post(f"/api/v1/track/report/{tracking.tracking_uuid}")
    assert again.json()["success"] is False


async def test_results_expose_the_captured_interaction(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """The authenticated results view returns the captured interaction."""
    tracking = await _seed_tracking(db, organization, employee, custom_template)
    await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}",
        json={
            "identifier": "jane.doe@acmetest.example",
            "password_length": 13,
            "fields": {"department": "Finance"},
        },
    )
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{tracking.campaign_id}/results",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["submitted"] == 1
    assert body["stats"]["submission_rate"] == 100.0
    row = body["employees"][0]
    assert row["status"] == "submitted"
    assert row["submitted_identifier"] == "jane.doe@acmetest.example"
    assert row["password_length"] == 13
    assert row["submitted_fields"] == {"department": "Finance"}
    assert row["submitted_at"] is not None
    assert row["immunity_score"] == 0.0
    assert row["behavioral_category"] == "critical_risk"
