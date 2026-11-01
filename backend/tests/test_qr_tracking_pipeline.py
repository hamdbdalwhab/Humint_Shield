"""Tests for end-to-end QR code tracking and integration with Elo engine.

Verifies the 5 steps required by the critical system directive:
Step 1: QR scan redirect and basic scan logging (/api/v1/track/qr/{campaign_id})
Step 2: Fingerprinting and submit payload
Step 3: Identity resolution, -25 Elo penalty, and unknown scan handling
Step 4: Training context and QR education verification
Step 5: Admin dashboard Radar / live scans verification
"""
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    QRScan,
    TrainingInteraction,
)


@pytest.fixture
def qr_campaign_factory(db: AsyncSession, organization: Organization, qr_template: EmailTemplate):
    async def _create(lure_type: str = "bonus"):
        campaign = EmailCampaign(
            organization_id=organization.id,
            template_id=qr_template.id,
            name=f"QR {lure_type.capitalize()} Campaign",
            status="active",
            channel="qr",
            channel_config={"qr": {"lure_type": lure_type, "pretext_key": lure_type}},
            target_employee_ids=[],
            total_targets=0,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        return campaign

    return _create


async def test_step1_qr_scan_logs_basic_event_and_redirects(client, db: AsyncSession, qr_campaign_factory):
    """Step 1: GET /api/v1/track/qr/{campaign_id} logs scan in tracking_events & qr_scans and redirects 302."""
    campaign = await qr_campaign_factory("bonus")

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "X-Forwarded-For": "198.51.100.42",
    }
    response = await client.get(f"/api/v1/track/qr/{campaign.id}", headers=headers, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert f"/qr/bonus/{campaign.id}" in location
    assert "tid=" in location

    # Verify basic scan event in tracking_events
    tracking_rows = (
        await db.execute(
            select(EmailTracking).where(
                EmailTracking.campaign_id == campaign.id,
                EmailTracking.channel == "qr",
            )
        )
    ).scalars().all()
    assert len(tracking_rows) == 1
    t_row = tracking_rows[0]
    assert t_row.last_ip_address == "198.51.100.42"
    assert "iPhone" in (t_row.last_user_agent or "")
    assert t_row.clicked_at is not None

    # Verify scan event in qr_scans
    scan_rows = (
        await db.execute(
            select(QRScan).where(
                QRScan.campaign_id == campaign.id,
            )
        )
    ).scalars().all()
    assert len(scan_rows) == 1
    s_row = scan_rows[0]
    assert s_row.tracking_id == t_row.id
    assert s_row.event_type == "qr_scanned"
    assert s_row.identity_resolution == "unknown"


async def test_step2_and_3_qr_submit_known_employee_penalizes_elo(client, db: AsyncSession, organization, employee, qr_campaign_factory):
    """Step 2 & 3: POST /api/v1/track/qr/submit resolves employee, updates tracking_events, applies -25 Elo, recalculates category."""
    employee.elo_score = 1000
    await db.commit()
    await db.refresh(employee)

    campaign = await qr_campaign_factory("hr")

    # Step 1: Scan first to simulate real flow
    scan_res = await client.get(f"/api/v1/track/qr/{campaign.id}", follow_redirects=False)
    assert scan_res.status_code == 302

    # Step 2: Submit credentials with device fingerprint
    fingerprint = {
        "screen": "390x844",
        "viewport": "390x664",
        "timezone": "Asia/Riyadh",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple GPU",
        "canvas_hash": "a1b2c3d4e5f6",
    }
    submit_payload = {
        "campaign_id": str(campaign.id),
        "username": employee.email.split("@")[0],
        "email": employee.email,
        "password_submitted": True,
        "fingerprint_data": fingerprint,
    }

    res = await client.post("/api/v1/track/qr/submit", json=submit_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["unknown"] is False
    assert data["resolved_employee_id"] == str(employee.id)
    assert data["elo_delta"] == -25
    assert data["tracking_uuid"] is not None

    # Verify employee Elo score dropped by 25
    await db.refresh(employee)
    assert employee.elo_score == 975
    assert employee.total_credential_submissions == 1

    # Verify tracking_events row was updated with employee_id and fields
    t_row = await db.scalar(
        select(EmailTracking).where(
            EmailTracking.campaign_id == campaign.id,
            EmailTracking.employee_id == employee.id,
        )
    )
    assert t_row is not None
    assert t_row.submitted_at is not None
    assert t_row.password_submitted is True
    assert t_row.qr_penalty_applied is True
    assert t_row.submitted_email == employee.email.lower()

    # Verify TrainingInteraction recorded
    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == t_row.id,
                TrainingInteraction.event_type == "qr_credential_submitted",
            )
        )
    ).scalars().all()
    assert len(interactions) == 1
    assert interactions[0].details["elo_delta"] == -25

    # Verify qr_scans record
    scans = (
        await db.execute(
            select(QRScan).where(
                QRScan.campaign_id == campaign.id,
                QRScan.employee_id == employee.id,
            )
        )
    ).scalars().all()
    assert len(scans) == 1
    scan = scans[0]
    assert scan.event_type == "qr_credential_submitted"
    assert scan.penalty_applied is True
    assert scan.elo_delta == -25
    assert scan.fingerprint_data["fingerprint_hash"] is not None


async def test_step3_qr_submit_unknown_employee_saved_as_unknown_scan(client, db: AsyncSession, qr_campaign_factory):
    """Step 3 (unknown): POST /api/v1/track/qr/submit with unknown user saves scan as Unknown without penalty."""
    campaign = await qr_campaign_factory("wifi")

    fingerprint = {
        "screen": "1920x1080",
        "timezone": "Europe/London",
        "canvas_hash": "canvas999",
    }
    submit_payload = {
        "campaign_id": str(campaign.id),
        "username": "external_visitor",
        "email": "visitor@external-agency.com",
        "password_submitted": True,
        "fingerprint_data": fingerprint,
    }

    res = await client.post("/api/v1/track/qr/submit", json=submit_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["unknown"] is True
    assert data["resolved_employee_id"] is None
    assert data["elo_delta"] == 0
    assert data["tracking_uuid"] is not None

    # Verify unknown scan in qr_scans
    scans = (
        await db.execute(
            select(QRScan).where(
                QRScan.campaign_id == campaign.id,
                QRScan.username == "external_visitor",
            )
        )
    ).scalars().all()
    assert len(scans) == 1
    scan = scans[0]
    assert scan.employee_id is None
    assert scan.identity_resolution == "unknown"
    assert scan.penalty_applied is False
    assert scan.fingerprint_data["fingerprint_hash"] is not None


async def test_step4_track_context_returns_qr_education(client, db: AsyncSession, organization, employee, qr_campaign_factory):
    """Step 4: GET /api/v1/track/context/{tracking_uuid} provides QR awareness context for landing & training."""
    campaign = await qr_campaign_factory("coffee")

    submit_payload = {
        "campaign_id": str(campaign.id),
        "username": employee.email.split("@")[0],
        "email": employee.email,
        "password_submitted": True,
        "fingerprint_data": {"screen": "414x896"},
    }
    submit_res = await client.post("/api/v1/track/qr/submit", json=submit_payload)
    tracking_uuid = submit_res.json()["tracking_uuid"]

    context_res = await client.get(f"/api/v1/track/context/{tracking_uuid}")
    assert context_res.status_code == 200
    ctx = context_res.json()
    assert ctx["found"] is True
    assert ctx["channel"] == "qr"
    assert ctx["qr_branding"] is not None
    assert ctx["qr_branding"]["lure_type"] == "coffee"


async def test_step5_admin_dashboard_radar_verification(client, db: AsyncSession, organization, employee, qr_campaign_factory, auth_headers):
    """Step 5: GET /api/v1/organizations/{org_id}/email-campaigns/{campaign_id}/scans shows employee, username, email, fp hash, IP."""
    campaign = await qr_campaign_factory("bonus")

    # 1. Record known employee submission
    await client.post(
        "/api/v1/track/qr/submit",
        headers={"X-Forwarded-For": "10.0.1.55"},
        json={
            "campaign_id": str(campaign.id),
            "username": "ahmed.khalid",
            "email": employee.email,
            "password_submitted": True,
            "fingerprint_data": {"screen": "1440x900", "timezone": "Asia/Riyadh"},
        },
    )

    # 2. Record unknown submission
    await client.post(
        "/api/v1/track/qr/submit",
        headers={"X-Forwarded-For": "192.168.1.100"},
        json={
            "campaign_id": str(campaign.id),
            "username": "guest_attacker",
            "email": "intruder@phish.xyz",
            "password_submitted": True,
            "fingerprint_data": {"screen": "800x600", "timezone": "UTC"},
        },
    )

    # Query admin scans endpoint (The Radar)
    radar_res = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/scans",
        headers=auth_headers,
    )
    assert radar_res.status_code == 200
    scans = radar_res.json()
    assert len(scans) >= 2

    # Check known scan
    known = next((s for s in scans if s["email"] == employee.email), None)
    assert known is not None
    assert known["employee_name"] == employee.full_name
    assert known["username"] == "ahmed.khalid"
    assert known["fingerprint_hash"] is not None
    assert known["ip_address"] == "10.0.1.55"
    assert known["elo_delta"] == -25
    assert known["penalty_applied"] is True

    # Check unknown scan
    unknown = next((s for s in scans if s["username"] == "guest_attacker"), None)
    assert unknown is not None
    assert unknown["employee_name"] is None
    assert unknown["email"] == "intruder@phish.xyz"
    assert unknown["fingerprint_hash"] is not None
    assert unknown["ip_address"] == "192.168.1.100"
    assert unknown["penalty_applied"] is False
