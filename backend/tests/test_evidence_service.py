"""Recipient-facing evidence report (`app.services.evidence_service`).

The report is the proof the training page shows: masked captured values, the
observed device/network, and the measured impact.  Tests assert that it never
leaks a password or a full identifier, and that the numbers add up.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset
from app.services.evidence_service import (
    build_evidence,
    describe_user_agent,
    mask_identifier,
    password_strength,
)

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-A536B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


def test_mask_identifier_keeps_shape_without_leaking() -> None:
    assert mask_identifier("hamedabdalfttah@gmail.com") == "ha*************@gmail.com"
    assert mask_identifier("+967770447622") == "+96********22"
    assert mask_identifier("") is None
    assert mask_identifier(None) is None


def test_password_strength_labels() -> None:
    assert password_strength(None) is None
    assert password_strength(0) is None
    assert password_strength(6) == "ضعيفة جدًا"
    assert password_strength(9) == "ضعيفة"
    assert password_strength(12) == "متوسطة"
    assert password_strength(20) == "قوية"


def test_describe_user_agent_identifies_mobile_device() -> None:
    parsed = describe_user_agent(ANDROID_UA)
    assert parsed["device"] == "هاتف محمول"
    assert parsed["os"] == "Android"
    assert parsed["browser"] == "Google Chrome"
    assert describe_user_agent(None) == {"browser": None, "os": None, "device": None}


async def _campaign_with_submission(
    db: AsyncSession,
    organization,
    employees: list[HumanAsset],
    *,
    channel: str = "sms",
) -> tuple[EmailCampaign, EmailTracking, HumanAsset]:
    """Create a launched SMS campaign whose recipient submitted credentials."""
    template = EmailTemplate(
        organization_id=organization.id,
        name="Evidence SMS",
        subject="تحقق أمني",
        body_html="<p>{{link}}</p>",
        channel=channel,
        difficulty_level=5,
        is_active=True,
        is_built_in=False,
        available_variables=["first_name", "link"],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    employee = employees[0]
    employee.elo_score = 1042
    employee.department = "IT"
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Evidence Campaign",
        channel=channel,
        status="completed",
        target_employee_ids=[str(e.id) for e in employees],
        total_targets=len(employees),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    clicked = datetime.now(timezone.utc) - timedelta(seconds=40)
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template.id,
        channel=channel,
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
        sent_at=clicked - timedelta(seconds=30),
        opened_at=clicked,
        clicked_at=clicked,
        submitted_at=clicked + timedelta(seconds=12),
        submission_count=1,
        submitted_identifier="hamedabdalfttah@gmail.com",
        password_length=9,
        last_ip_address="203.0.113.42",
        last_user_agent=ANDROID_UA,
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return campaign, tracking, employee


@pytest.mark.asyncio
async def test_evidence_reports_masked_capture_and_impact(
    db: AsyncSession, organization, employees
) -> None:
    """The report proves what was captured without storing or leaking it."""
    campaign, tracking, employee = await _campaign_with_submission(
        db, organization, employees
    )

    report = await build_evidence(db, tracking.tracking_uuid)

    assert report["found"] is True
    assert report["channel"] == "sms"
    captured = report["captured"]
    assert captured["submitted"] is True
    assert captured["identifier_masked"].endswith("@gmail.com")
    assert "hamedabdalfttah" not in captured["identifier_masked"]
    assert captured["password_length"] == 9
    assert captured["password_strength"] == "ضعيفة"
    assert "كلمة المرور" in captured["fields"]
    assert captured["seconds_to_submit"] == 12.0
    # Only the length is reported: the typed password is never part of the
    # payload, so a leaked tracking UUID cannot expose a credential.
    assert set(captured) == {
        "submitted",
        "identifier_masked",
        "email_masked",
        "password_length",
        "password_strength",
        "otp_submitted",
        "fields",
        "submitted_at",
        "attempts",
        "seconds_to_submit",
        "storage_note",
    }

    attacker = report["attacker_view"]
    assert attacker["device"] == "هاتف محمول"
    assert attacker["browser"] == "Google Chrome"
    assert attacker["ip_address"] == "203.0.113.42"

    impact = report["impact"]
    assert impact["elo_now"] == int(employee.elo_score)
    assert impact["elo_delta"] == -40
    assert impact["elo_before"] == impact["elo_now"] + 40
    assert impact["department_targeted"] >= 1
    assert impact["org_targeted"] >= 1
    assert report["next_steps"]


@pytest.mark.asyncio
async def test_evidence_hides_everything_for_unknown_tracking() -> None:
    """An unknown or malformed UUID returns a bare not-found payload."""
    assert await build_evidence(None, "not-a-uuid") == {"found": False}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_evidence_for_unsubmitted_recipient_has_no_penalty(
    db: AsyncSession, organization, employees
) -> None:
    """A recipient who only clicked shows the observation without a score cut."""
    campaign, tracking, employee = await _campaign_with_submission(
        db, organization, employees
    )
    tracking.submitted_at = None
    tracking.submitted_identifier = None
    tracking.password_length = None
    await db.commit()

    report = await build_evidence(db, tracking.tracking_uuid)

    assert report["captured"]["submitted"] is False
    assert report["captured"]["identifier_masked"] is None
    assert report["impact"]["elo_delta"] == 0
