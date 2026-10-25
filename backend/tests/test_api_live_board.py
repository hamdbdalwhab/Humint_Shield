"""API tests: the live campaign monitoring board.

The board is what an operator watches immediately after launching: one card per
recipient, the current funnel status, every transition timestamp, the seconds
between transitions, and the newest activity in the campaign.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTracking, Organization


async def _campaign_with_recipients(
    db: AsyncSession,
    organization: Organization,
    employees,
    template,
    *,
    launched: bool = True,
) -> tuple[EmailCampaign, list[EmailTracking]]:
    """Create a campaign with one tracking row per employee."""
    now = datetime.now(timezone.utc)
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Live Board Campaign",
        status="completed" if launched else "draft",
        target_employee_ids=[str(employee.id) for employee in employees],
        total_targets=len(employees),
        sent_count=len(employees) if launched else 0,
        launched_at=now - timedelta(minutes=2) if launched else None,
    )
    db.add(campaign)
    await db.flush()

    trackings = []
    for employee in employees:
        tracking = EmailTracking(
            campaign_id=campaign.id,
            employee_id=employee.id,
            email_template_id=template.id,
            tracking_uuid=uuid.uuid4(),
            sent_at=now - timedelta(seconds=60) if launched else None,
            delivered_at=now - timedelta(seconds=59) if launched else None,
        )
        db.add(tracking)
        trackings.append(tracking)
    await db.commit()
    await db.refresh(campaign)
    for tracking in trackings:
        await db.refresh(tracking)
    return campaign, trackings


async def test_live_board_reports_every_recipient_state(
    client, db, organization, employees, custom_template, auth_headers
) -> None:
    """Three recipients at three different stages are reported precisely."""
    targets = employees[:3]
    campaign, trackings = await _campaign_with_recipients(
        db, organization, targets, custom_template
    )
    first, second, third = trackings

    # First recipient: open -> click -> form -> submit.
    assert (await client.get(f"/api/v1/track/open/{first.tracking_uuid}")).status_code == 200
    assert (
        await client.get(f"/api/v1/track/click/{first.tracking_uuid}", follow_redirects=False)
    ).status_code == 302
    assert (await client.get(f"/training-legacy/{first.tracking_uuid}")).status_code == 200
    assert (
        await client.post(
            f"/api/v1/track/submit/{first.tracking_uuid}",
            json={
                "identifier": targets[0].email,
                "password": "Passw0rd!",
                "password_length": 9,
                "fields": {"password": "Passw0rd!", "department": "Finance"},
                "client": {"seconds_on_form": 12},
            },
        )
    ).status_code == 200

    # Third recipient: opened only.  Second recipient stays untouched.
    assert (await client.get(f"/api/v1/track/open/{third.tracking_uuid}")).status_code == 200

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/live",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["campaign"]["id"] == str(campaign.id)
    assert body["campaign"]["template_name"] == custom_template.name
    assert body["campaign"]["launched_at"] is not None

    by_email = {row["email"]: row for row in body["recipients"]}
    assert len(by_email) == 3
    assert by_email[targets[0].email]["status"] == "submitted"
    assert by_email[targets[1].email]["status"] == "sent"
    assert by_email[targets[2].email]["status"] == "opened"

    submitted = by_email[targets[0].email]
    assert submitted["open_count"] == 1
    assert submitted["click_count"] == 1
    assert submitted["submission_count"] == 1
    assert submitted["interactions_count"] >= 4
    assert submitted["password_length"] == 9
    assert submitted["last_event_type"] == "form_submitted"
    assert submitted["last_event_label"] == "Credentials entered"
    assert submitted["seconds_to_open"] is not None
    assert 0 < submitted["seconds_to_open"] <= 120
    assert submitted["seconds_to_submit"] >= submitted["seconds_to_open"]

    summary = body["summary"]
    assert summary["total"] == 3
    assert summary["sent"] == 3
    assert summary["opened"] == 2
    assert summary["clicked"] == 1
    assert summary["form_viewed"] == 1
    assert summary["submitted"] == 1
    assert summary["failed"] == 0
    assert summary["open_rate"] == 66.67
    assert summary["click_rate"] == 33.33
    assert summary["avg_seconds_to_open"] is not None

    # Newest event first in the ticker.
    events = body["recent_events"]
    assert events
    assert events[0]["event_type"] == "email_open"
    assert events[0]["employee_name"] == targets[2].full_name
    assert all(event["seconds_ago"] >= 0 for event in events)


async def test_live_board_reconstructs_legacy_rows_without_ledger(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """A tracking row with no ledger entries still shows a last event."""
    campaign, trackings = await _campaign_with_recipients(
        db, organization, [employee], custom_template
    )
    tracking = trackings[0]
    tracking.opened_at = tracking.sent_at + timedelta(seconds=8)
    await db.commit()

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/live",
        headers=auth_headers,
    )
    assert response.status_code == 200
    row = response.json()["recipients"][0]
    assert row["status"] == "opened"
    assert row["last_event_type"] == "email_opened"
    assert row["seconds_to_open"] == 8.0
    assert row["interactions_count"] == 0
    assert response.json()["recent_events"] == []


async def test_live_board_marks_unlaunched_campaign_as_pending(
    client, db, organization, employee, custom_template, auth_headers
) -> None:
    """A draft campaign shows pending recipients, not failures."""
    campaign, _ = await _campaign_with_recipients(
        db, organization, [employee], custom_template, launched=False
    )
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/live",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recipients"][0]["status"] == "pending"
    assert body["summary"]["pending"] == 1
    assert body["summary"]["sent"] == 0


async def test_live_board_unknown_campaign_returns_404(
    client, organization, auth_headers
) -> None:
    """An unknown campaign id is a 404, never an empty board."""
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{uuid.uuid4()}/live",
        headers=auth_headers,
    )
    assert response.status_code == 404
