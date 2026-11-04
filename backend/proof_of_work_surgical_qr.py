"""Surgical Fix Verification Protocol for QR Channel."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
import httpx
from sqlalchemy import select

from app.database import get_session_factory
from app.models import EmailCampaign, EmailTemplate, HumanAsset, Organization, User
from app.security import create_access_token


async def run_protocol():
    print("=" * 80)
    print("SURGICAL FIX VERIFICATION: QR CHANNEL FULL PIPELINE TEST")
    print("=" * 80)

    session_factory = get_session_factory()
    async with session_factory() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        template = (await db.execute(select(EmailTemplate).where(EmailTemplate.channel == "qr"))).scalars().first()
        if not template:
            template = (await db.execute(select(EmailTemplate))).scalars().first()
        employee = (await db.execute(select(HumanAsset).order_by(HumanAsset.created_at.desc()))).scalars().first()
        user = (await db.execute(select(User))).scalars().first()

        assert org and template and employee and user

        initial_elo = employee.elo_score
        emp_email = employee.email
        emp_username = emp_email.split("@")[0]

        # 1. Create a Generic QR Campaign (No employees selected!)
        campaign = EmailCampaign(
            organization_id=org.id,
            template_id=template.id,
            name=f"Generic QR Lure {uuid.uuid4().hex[:6]}",
            status="active",
            channel="qr",
            channel_config={
                "qr": {
                    "lure_type": "hr",
                    "pretext_key": "hr",
                    "company_name": "Acme Cyber Corp",
                    "department": "Security",
                }
            },
            target_employee_ids=[],
            total_targets=0,
            sent_count=0,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        campaign_id = str(campaign.id)
        user_token = create_access_token(str(user.id), extra={"org_id": str(org.id), "role": "admin"})

    print(f"\n[PHASE 1] Campaign Created (Generic Lure - No Targets):")
    print(f"  - Campaign ID:       {campaign_id}")
    print(f"  - Channel:           qr")
    print(f"  - Targets Count:     0 (Generic Lure)")
    print(f"  - Target Employee:   {employee.first_name} {employee.last_name}")
    print(f"  - Employee Email:    {emp_email}")
    print(f"  - Initial Elo Score: {initial_elo}")

    client_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
        "X-Forwarded-For": "185.191.171.42",
    }

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as http:
        # Step A: Download PDF poster
        auth_headers = {"Authorization": f"Bearer {user_token}"}
        pdf_res = await http.post(f"/api/v1/campaigns/{campaign_id}/generate-qr", headers=auth_headers)
        print(f"\n[PHASE 2] PDF Poster Generation (POST /api/v1/campaigns/{campaign_id}/generate-qr):")
        print(f"  - Status Code: {pdf_res.status_code}")
        print(f"  - Content-Type: {pdf_res.headers.get('content-type')}")
        print(f"  - Content-Length: {len(pdf_res.content)} bytes")
        assert pdf_res.status_code == 200
        assert pdf_res.headers.get("content-type") == "application/pdf"
        assert len(pdf_res.content) > 1000

        # Step B: Scan QR Code (Hit GET /api/v1/track/qr/{campaign_id})
        scan_res = await http.get(f"/api/v1/track/qr/{campaign_id}", headers=client_headers, follow_redirects=False)
        print(f"\n[PHASE 3] QR Scan Hit (GET /api/v1/track/qr/{campaign_id}):")
        print(f"  - Status Code: {scan_res.status_code}")
        print(f"  - Location Header (302 Redirect): {scan_res.headers.get('location')}")
        assert scan_res.status_code == 302
        redirect_url = scan_res.headers.get("location")
        assert f"/qr/" in redirect_url and campaign_id in redirect_url

        # Step C: Form Submission (POST /api/v1/track/qr/submit)
        submit_payload = {
            "campaign_id": campaign_id,
            "username": emp_username,
            "email": emp_email,
            "fingerprint_data": {
                "os": "iOS",
                "browser": "Safari Mobile",
                "screen": "393x852",
                "fingerprint_hash": "a1b2c3d4e5f67890abcdef1234567890",
            },
        }
        submit_res = await http.post("/api/v1/track/qr/submit", json=submit_payload, headers=client_headers)
        print(f"\n[PHASE 4] Form Submission (POST /api/v1/track/qr/submit):")
        print(f"  - Status Code: {submit_res.status_code}")
        submit_data = submit_res.json()
        print(f"  - Response JSON:\n{json.dumps(submit_data, indent=2)}")
        assert submit_res.status_code == 200
        assert submit_data.get("success") is True
        assert "/training/" in (submit_data.get("redirect") or submit_data.get("redirect_url"))

        # Step D: Live Radar Polling (GET /api/v1/campaigns/{campaign_id}/scans)
        radar_res = await http.get(f"/api/v1/campaigns/{campaign_id}/scans", headers=auth_headers)
        print(f"\n[PHASE 5] Live Radar Scans (GET /api/v1/campaigns/{campaign_id}/scans):")
        print(f"  - Status Code: {radar_res.status_code}")
        radar_scans = radar_res.json()
        print(f"  - Scans Count: {len(radar_scans)}")
        assert len(radar_scans) >= 1
        latest_scan = radar_scans[0]
        print(f"  - Latest Scan Card Data:")
        print(f"      Time:             {latest_scan.get('occurred_at')}")
        print(f"      IP:               {latest_scan.get('ip_address')}")
        print(f"      Device Model/OS:  {latest_scan.get('device_model') or latest_scan.get('fingerprint', {}).get('os')}")
        print(f"      Fingerprint Hash: {latest_scan.get('fingerprint_hash')}")
        print(f"      Entered Username: {latest_scan.get('username') or latest_scan.get('username_entered')}")
        print(f"      Entered Email:    {latest_scan.get('email') or latest_scan.get('email_entered')}")
        print(f"      Matched Employee: {latest_scan.get('employee_name')} (ID: {latest_scan.get('employee_id')})")
        print(f"      Elo Delta:        {latest_scan.get('elo_delta')}")
        assert latest_scan.get("employee_name") is not None
        assert latest_scan.get("elo_delta") == -25

    # Step E: Verify Database State & Elo Deduction
    async with session_factory() as db:
        updated_employee = await db.get(HumanAsset, employee.id)
        final_elo = updated_employee.elo_score
        print(f"\n[PHASE 6] Elo Score Verification:")
        print(f"  - Initial Elo:  {initial_elo}")
        print(f"  - Final Elo:    {final_elo}")
        print(f"  - Net Delta:    {final_elo - initial_elo} (Expected: -25.0)")
        assert (final_elo - initial_elo) == -25

    # Step F: SQLite Raw Tables Inspection
    print(f"\n[PHASE 7] Raw SQLite Database Rows:")
    conn = sqlite3.connect("humint_dev.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, campaign_id, event_type, last_ip_address, submitted_username, submitted_email, created_at 
        FROM tracking_events 
        WHERE campaign_id = ?
        ORDER BY created_at DESC;
    """, (uuid.UUID(campaign_id).hex,))
    te_rows = cursor.fetchall()
    print(f"  - tracking_events rows ({len(te_rows)}):")
    for r in te_rows:
        print(f"      id={r[0]}, event_type={r[2]}, ip={r[3]}, username={r[4]}, email={r[5]}")

    cursor.execute("""
        SELECT id, campaign_id, event_type, ip_address, username, email, occurred_at 
        FROM qr_scans 
        WHERE campaign_id = ?
        ORDER BY occurred_at DESC;
    """, (uuid.UUID(campaign_id).hex,))
    qs_rows = cursor.fetchall()
    print(f"  - qr_scans rows ({len(qs_rows)}):")
    for r in qs_rows:
        print(f"      id={r[0]}, event_type={r[2]}, ip={r[3]}, username={r[4]}, email={r[5]}")
    conn.close()

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED WITH 100% SUCCESS! SURGICAL FIX COMPLETE.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_protocol())
