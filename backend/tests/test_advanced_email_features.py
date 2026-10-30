"""Tests for Advanced Email Channel features:
1. Module 1: MFA (OTP) bypass simulation and -15 Elo penalty
2. Module 2: Custom URL shortener (/s/{short_code}) and link rewriting
3. Module 3: Automated drip re-test campaign for failed employees
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset, TrainingInteraction
from app.services.elo_engine import OTP_SUBMISSION_ELO_DELTA
from app.services.template_service import TemplatePersonalizer
from app.services.tracking_service import TrackingService
from app.worker.tasks import execute_retest_failed_employees, retest_failed_campaign_employees


async def _seed_test_campaign(
    db: AsyncSession,
    organization,
    employee,
    template,
    *,
    channel: str = "email",
    auto_retest: bool = False,
) -> tuple[EmailCampaign, EmailTracking]:
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Advanced Email Test Campaign",
        status="completed",
        channel=channel,
        auto_retest_failed=auto_retest,
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
    )
    db.add(campaign)
    await db.flush()

    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template.id,
        channel=channel,
        tracking_uuid=uuid.uuid4(),
        short_code="aB3x9Z",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(campaign)
    await db.refresh(tracking)
    return campaign, tracking


async def test_otp_submission_applies_elo_penalty(client, db, organization, employee, custom_template):
    """Submitting OTP records otp_submitted, interaction event, and applies -15 Elo penalty."""
    employee.elo_score = 1000
    await db.commit()

    _, tracking = await _seed_test_campaign(db, organization, employee, custom_template)

    # Context initially reflects otp_submitted=False
    ctx_res = await client.get(f"/api/v1/track/context/{tracking.tracking_uuid}")
    assert ctx_res.status_code == 200
    assert ctx_res.json()["otp_submitted"] is False

    # Submit OTP
    res = await client.post(
        f"/api/v1/track/otp/{tracking.tracking_uuid}",
        json={"otp_code": "123456"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # Refresh and verify tracking record
    await db.refresh(tracking)
    assert tracking.otp_submitted is True
    assert tracking.otp_submitted_at is not None

    # Verify employee Elo score dropped by 15
    await db.refresh(employee)
    assert employee.elo_score == 1000 + OTP_SUBMISSION_ELO_DELTA  # 985

    # Verify TrainingInteraction recorded
    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "otp_submitted",
            )
        )
    ).scalars().all()
    assert len(interactions) == 1
    assert interactions[0].details["otp_length"] == 6
    assert interactions[0].details["elo_delta"] == -15

    # Context now returns otp_submitted=True
    ctx_res_after = await client.get(f"/api/v1/track/context/{tracking.tracking_uuid}")
    assert ctx_res_after.json()["otp_submitted"] is True


async def test_short_url_redirect_and_click_tracking(client, db, organization, employee, custom_template):
    """GET /s/{short_code} accurately tracks click and 302 redirects to /phish/{uuid}."""
    _, tracking = await _seed_test_campaign(db, organization, employee, custom_template)
    assert tracking.click_count == 0
    assert tracking.clicked_at is None

    # Request short URL
    response = await client.get(f"/s/{tracking.short_code}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].endswith(f"/phish/{tracking.tracking_uuid}")

    # Check click was recorded
    await db.refresh(tracking)
    assert tracking.click_count == 1
    assert tracking.clicked_at is not None

    # Check click interaction in ledger
    clicks = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "link_click",
            )
        )
    ).scalars().all()
    assert len(clicks) == 1


async def test_template_personalizer_uses_short_url(organization, employee, custom_template):
    """TemplatePersonalizer rewrites links using the short URL when provided."""
    personalizer = TemplatePersonalizer()
    custom_template.body_html = '<p>Please <a href="https://example.com/login">click here</a>.</p>'
    tracking_uuid = uuid.uuid4()
    short_code = "xyz123"

    rendered = personalizer.personalize(
        custom_template,
        employee,
        organization,
        tracking_uuid,
        short_code=short_code,
    )

    assert f"/s/{short_code}" in rendered["html_content"]
    assert 'href="https://example.com/login"' not in rendered["html_content"]


async def test_automated_drip_retest_task(db, organization, employee, custom_template):
    """retest_failed_campaign_employees finds failed employees and launches new harder campaign."""
    # Create harder template
    harder_template = EmailTemplate(
        organization_id=organization.id,
        name="Advanced Executive Spearphish",
        subject="Confidential wire request",
        body_html="<p>Wire instructions attached.</p>",
        channel="email",
        difficulty_level=8,
        is_active=True,
    )
    db.add(harder_template)
    await db.flush()

    # Create campaign with auto_retest enabled
    campaign, tracking = await _seed_test_campaign(
        db, organization, employee, custom_template, auto_retest=True
    )
    # Simulate employee failing by clicking
    tracking.clicked_at = datetime.now(timezone.utc)
    tracking.click_count = 1
    await db.commit()

    # Run drip campaign retest logic
    result = await execute_retest_failed_employees(campaign.id, db)
    assert result["status"] == "success"
    assert result["targets_count"] == 1
    assert result["difficulty"] == 8

    # Verify the new drip campaign in the database
    new_cid = uuid.UUID(result["new_campaign_id"])
    new_campaign = await db.get(EmailCampaign, new_cid)
    assert new_campaign is not None
    assert "Retest" in new_campaign.name
    assert new_campaign.template_id == harder_template.id
    assert new_campaign.target_employee_ids == [str(employee.id)]
    assert new_campaign.total_targets == 1


async def test_shortener_invalid_and_missing(client):
    """GET /s/{short_code} handles 404 cleanly for invalid or missing codes."""
    res = await client.get("/s/nonexistent123")
    assert res.status_code == 404

    res2 = await client.get("/s/" + "x" * 25)
    assert res2.status_code == 404


async def test_otp_submission_invalid_uuid(client):
    """POST /api/v1/track/otp/{invalid_uuid} returns failure response."""
    res = await client.post("/api/v1/track/otp/not-a-uuid", json={"otp_code": "123456"})
    assert res.status_code == 200
    assert res.json()["success"] is False

    res_unknown = await client.post(f"/api/v1/track/otp/{uuid.uuid4()}", json={"otp_code": "123456"})
    assert res_unknown.status_code == 200
    assert res_unknown.json()["success"] is False


async def test_campaign_create_with_auto_retest(client, db, organization, custom_template, employee, auth_headers):
    """POST /api/v1/organizations/{org_id}/email-campaigns respects auto_retest_failed parameter."""
    res = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        headers=auth_headers,
        json={
            "name": "Auto Retest Campaign",
            "template_id": str(custom_template.id),
            "channel": "email",
            "auto_retest_failed": True,
            "target_employee_ids": [str(employee.id)],
        },
    )
    assert res.status_code == 201
    cid = res.json()["id"]
    campaign = await db.get(EmailCampaign, uuid.UUID(cid))
    assert campaign is not None
    assert campaign.auto_retest_failed is True

    # Update auto_retest_failed
    res_update = await client.put(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{cid}",
        headers=auth_headers,
        json={"auto_retest_failed": False},
    )
    assert res_update.status_code == 200
    assert res_update.json()["auto_retest_failed"] is False
