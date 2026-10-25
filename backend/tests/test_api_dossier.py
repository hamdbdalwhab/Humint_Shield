"""API tests: the per-employee dossier and per-recipient campaign record.

These cover the "prove exactly what happened" surface:

* the complete interaction ledger (every open, click, form render, submission,
  report and completion with exact timestamps),
* decrypted evidence of every value an employee typed, and
* the campaign-wide audit feed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTracking, Organization


async def _seed(
    db: AsyncSession, organization: Organization, employee, template, *, name: str = "Dossier Campaign"
) -> tuple[EmailCampaign, EmailTracking]:
    """Create a campaign plus one tracking row and return both."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=name,
        status="completed",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
        opened_count=1,
        clicked_count=1,
    )
    db.add(campaign)
    await db.flush()
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
    await db.refresh(campaign)
    return campaign, tracking


async def _full_interaction(client, tracking: EmailTracking) -> None:
    """Drive a recipient through open -> click -> submit -> report -> complete."""
    uid = tracking.tracking_uuid
    assert (await client.get(f"/api/v1/track/open/{uid}")).status_code == 200
    redirect = await client.get(f"/api/v1/track/click/{uid}", follow_redirects=False)
    assert redirect.status_code == 302
    page = await client.get(f"/training-legacy/{uid}")
    assert page.status_code == 200
    assert "Verify your identity" in page.text
    submit = await client.post(
        f"/api/v1/track/submit/{uid}",
        json={
            "identifier": "dossier.user@acmetest.example",
            "password": "Passw0rd!",
            "password_length": 9,
            "fields": {"password": "Passw0rd!", "department": "Finance"},
            "client": {"seconds_on_form": 14, "timezone": "Africa/Cairo"},
        },
    )
    assert submit.status_code == 200
    report = await client.post(f"/api/v1/track/report/{uid}")
    assert report.status_code == 200
    complete = await client.post(f"/api/v1/track/complete/{uid}")
    assert complete.status_code == 200


async def test_employee_dossier_contains_every_event_and_typed_value(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """The dossier proves what was typed, when, and from where."""
    campaign, tracking = await _seed(db, organization, employee, custom_template)
    await _full_interaction(client, tracking)

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}/dossier",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["employee"]["id"] == str(employee.id)
    assert body["summary"]["campaigns"] == 1
    assert body["summary"]["submitted"] == 1
    assert body["summary"]["reported"] == 1
    assert body["summary"]["completed"] == 1
    assert body["summary"]["emails_sent"] == 1

    record = body["campaigns"][0]
    assert record["campaign_id"] == str(campaign.id)
    assert record["status"] == "completed"
    # The verbatim payload, including the password, is returned.
    assert record["submitted_values"] == {
        "identifier": "dossier.user@acmetest.example",
        "password": "Passw0rd!",
        "department": "Finance",
    }
    # The plain snapshot stays secret-free.
    assert record["submitted_fields"] == {"department": "Finance"}
    assert record["client_context"] == {"seconds_on_form": 14, "timezone": "Africa/Cairo"}
    assert record["submission_count"] == 1

    event_types = [event["event_type"] for event in record["events"]]
    assert event_types == [
        "email_open",
        "link_click",
        "form_viewed",
        "form_submitted",
        "phishing_reported",
        "training_completed",
    ]
    # Exact timestamps, ordered, with server-side attribution.
    occurred = [event["occurred_at"] for event in record["events"]]
    assert occurred == sorted(occurred)
    for event in record["events"]:
        assert event["occurred_at"]
        assert event["ip_address"]
        assert event["user_agent"]

    submission = record["submissions"][0]
    assert submission["values"]["password"] == "Passw0rd!"
    assert submission["password_length"] == 9
    assert submission["client"] == {"seconds_on_form": 14, "timezone": "Africa/Cairo"}
    # The merged view mirrors the per-campaign record.
    assert [event["event_type"] for event in body["events"]] == event_types
    assert all(event["campaign_name"] == campaign.name for event in body["events"])
    assert body["submissions"][0]["values"]["identifier"] == "dossier.user@acmetest.example"


async def test_campaign_recipient_record_and_activity_feed(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """The campaign-scoped views expose the same precise record."""
    campaign, tracking = await _seed(db, organization, employee, custom_template)
    await _full_interaction(client, tracking)

    detail = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}"
        f"/recipients/{employee.id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["campaign"]["id"] == str(campaign.id)
    assert payload["employee"]["id"] == str(employee.id)
    assert payload["record"]["submitted_values"]["password"] == "Passw0rd!"

    activity = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/activity",
        headers=auth_headers,
    )
    assert activity.status_code == 200
    feed = activity.json()
    assert feed["campaign"]["id"] == str(campaign.id)
    assert len(feed["events"]) == 6
    assert all(event["employee_email"] == employee.email for event in feed["events"])
    submitted = next(e for e in feed["events"] if e["event_type"] == "form_submitted")
    assert submitted["values"]["password"] == "Passw0rd!"


async def test_dossier_unknown_employee_and_foreign_recipient(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """Unknown employees and non-recipients are 404, never a leak."""
    missing = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{uuid.uuid4()}/dossier",
        headers=auth_headers,
    )
    assert missing.status_code == 404

    campaign, _ = await _seed(db, organization, employee, custom_template)
    other = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}"
        f"/recipients/{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert other.status_code == 404


async def test_campaign_results_include_submitted_values(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """The live results table carries the decrypted evidence too."""
    campaign, tracking = await _seed(db, organization, employee, custom_template)
    await _full_interaction(client, tracking)

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/results",
        headers=auth_headers,
    )
    assert response.status_code == 200
    rows = response.json()["employees"]
    assert len(rows) == 1
    assert rows[0]["submitted_values"] == {
        "identifier": "dossier.user@acmetest.example",
        "password": "Passw0rd!",
        "department": "Finance",
    }
    assert rows[0]["form_viewed_at"] is not None


async def test_campaign_csv_export_includes_typed_values(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """CSV export contains the full typed payload column."""
    campaign, tracking = await _seed(db, organization, employee, custom_template)
    await _full_interaction(client, tracking)

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/export",
        headers=auth_headers,
    )
    assert response.status_code == 200
    text = response.text
    assert "submitted_values_json" in text
    assert "Passw0rd!" in text
    assert "form_viewed_at" in text


async def test_legacy_tracking_row_without_ledger_is_still_reported(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """Rows created before the ledger existed are reconstructed from timestamps."""
    campaign, tracking = await _seed(db, organization, employee, custom_template)
    now = datetime.now(timezone.utc)
    tracking.created_at = now - timedelta(minutes=5)
    tracking.delivered_at = now
    tracking.opened_at = now
    tracking.clicked_at = now
    tracking.form_viewed_at = now
    tracking.form_submitted_at = now
    tracking.submitted_identifier = "legacy.user@acmetest.example"
    tracking.password_length = 8
    tracking.submission_count = 1
    await db.commit()

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/employees/{employee.id}/dossier",
        headers=auth_headers,
    )
    assert response.status_code == 200
    record = response.json()["campaigns"][0]
    assert record["status"] == "submitted"
    # Reconstructed ledger keeps the original order.
    assert [event["event_type"] for event in record["events"]] == [
        "campaign_assigned",
        "email_sent",
        "email_delivered",
        "email_opened",
        "link_clicked",
        "training_form_viewed",
        "credentials_submitted",
    ]
    assert all(event["details"].get("synthetic") for event in record["events"][1:])
    # Whatever the legacy row still holds is surfaced.
    assert record["submitted_values"] == {"identifier": "legacy.user@acmetest.example"}
    assert record["submissions"][0]["password_length"] == 8
    assert record["submissions"][0]["campaign_name"] == campaign.name
    assert record["events"][-1]["values"] == {"identifier": "legacy.user@acmetest.example"}

    # The campaign-wide feed reconstructs the same history.
    activity = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/activity",
        headers=auth_headers,
    )
    assert activity.status_code == 200
    feed = activity.json()["events"]
    assert [event["event_type"] for event in feed] == [
        "campaign_assigned",
        "email_sent",
        "email_delivered",
        "email_opened",
        "link_clicked",
        "training_form_viewed",
        "credentials_submitted",
    ]
    assert feed[0]["employee_email"] == employee.email
    assert all(event["employee_name"] for event in feed)
