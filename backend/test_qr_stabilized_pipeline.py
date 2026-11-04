"""End-to-End Verification of Stabilized QR Channel Flow (REST & Polling)."""
from __future__ import annotations

import asyncio
import json
import uuid
import httpx
from sqlalchemy import select

from app.database import get_session_factory
from app.models import EmailCampaign, EmailTemplate, HumanAsset, Organization, QRScan, EmailTracking, User
from app.security import create_access_token


async def main():
    print("=" * 75)
    print("STARTING E2E VERIFICATION: STABILIZED QR CHANNEL FLOW (HTTP REST)")
    print("=" * 75)

    session_factory = get_session_factory()
    async with session_factory() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        template = (await db.execute(select(EmailTemplate))).scalars().first()
        employee = (await db.execute(select(HumanAsset).order_by(HumanAsset.created_at.desc()))).scalars().first()

        user = (await db.execute(select(User))).scalars().first()
        assert org and template and employee and user
        initial_elo = employee.elo_score

        # 1. Create QR campaign
        campaign = EmailCampaign(
            organization_id=org.id,
            template_id=template.id,
            name=f"Stabilized QR Verification {uuid.uuid4().hex[:6]}",
            status="active",
            channel="qr",
            channel_config={"qr": {"lure_type": "wifi", "pretext_key": "wifi"}},
            target_employee_ids=[],
            total_targets=0,
            sent_count=0,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        campaign_id = campaign.id
        print(f"\n[1] Campaign Created Successfully:")
        print(f"    - Campaign ID: {campaign_id}")
        print(f"    - Name: '{campaign.name}'")
        print(f"    - Channel: {campaign.channel} (Lure: wifi)")
        print(f"    - Target Employee: {employee.first_name} {employee.last_name} ({employee.email}) | Elo: {initial_elo}")

    token = create_access_token(str(user.id), extra={"org_id": str(org.id), "role": "admin"})
    auth_headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 2. Check Live Radar BEFORE scans: should return empty list (No scans yet)
        res_radar_0 = await client.get(f"/api/v1/campaigns/{campaign_id}/scans", headers=auth_headers)
        assert res_radar_0.status_code == 200, f"Expected 200, got {res_radar_0.status_code}: {res_radar_0.text}"
        scans_0 = res_radar_0.json()
        print(f"\n[2] Initial Live Radar Polling Check (Before scans):")
        print(f"    - HTTP GET /api/v1/campaigns/{campaign_id}/scans: {res_radar_0.status_code}")
        print(f"    - Scans Count: {len(scans_0)} (Shows 'No scans yet' on Dashboard)")
        assert len(scans_0) == 0

        # 3. Simulate QR Scan / Opening QR link: GET /api/v1/track/qr/{campaign_id}
        mobile_ua = "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"
        scan_headers = {
            "User-Agent": mobile_ua,
            "X-Forwarded-For": "175.110.45.10",
        }
        res_scan = await client.get(f"/api/v1/track/qr/{campaign_id}", headers=scan_headers, follow_redirects=False)
        print(f"\n[3] User Scans QR Code (GET /api/v1/track/qr/{campaign_id}):")
        print(f"    - HTTP Status: {res_scan.status_code} (Redirect to Landing Page)")
        redirect_location = res_scan.headers.get("location")
        print(f"    - Redirect Location: {redirect_location}")
        assert res_scan.status_code in (302, 307)
        assert f"/qr/wifi/{campaign_id}" in (redirect_location or "")

        # 4. Check Live Radar Polling: Scan recorded!
        res_radar_1 = await client.get(f"/api/v1/campaigns/{campaign_id}/scans", headers=auth_headers)
        assert res_radar_1.status_code == 200
        scans_1 = res_radar_1.json()
        print(f"\n[4] Live Radar Polling Check (After QR scan, before form submission):")
        print(f"    - Scans Count: {len(scans_1)}")
        assert len(scans_1) == 1
        s1 = scans_1[0]
        print(f"    - Scan ID: {s1['id']}")
        print(f"    - Device Model: {s1.get('device_model')}")
        print(f"    - Geo Location: {s1.get('city')}, {s1.get('country')} (ISP: {s1.get('isp')})")
        print(f"    - IP Address: {s1.get('ip_address')}")
        print(f"    - Event Type: {s1.get('event_type')}")
        assert s1.get("device_model") == "Samsung Galaxy S23"
        assert s1.get("city") == "Sanaa"
        assert s1.get("country") == "Yemen"
        assert s1.get("ip_address") == "175.110.45.10"

        # 5. User fills the form on Landing Page and Submits: POST /api/v1/track/qr/submit
        submit_payload = {
            "campaign_id": str(campaign_id),
            "username": employee.email.split("@")[0],
            "email": employee.email,
            "password_submitted": True,
            "fingerprint_data": {
                "screen": "393x852",
                "device_model": "SM-S911B",
                "platform": "Linux armv8l",
                "fingerprint_hash": "b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
            },
            "fields": {"lure_type": "wifi", "portal": "qr-wifi"},
        }
        res_submit = await client.post(
            "/api/v1/track/qr/submit",
            json=submit_payload,
            headers=scan_headers,
        )
        print(f"\n[5] Form Submission (POST /api/v1/track/qr/submit):")
        print(f"    - HTTP Status: {res_submit.status_code}")
        assert res_submit.status_code == 200, f"Expected 200, got: {res_submit.text}"
        data_submit = res_submit.json()
        print(f"    - Response Status: {data_submit.get('status')}")
        print(f"    - Redirect URL: {data_submit.get('redirect_url')}")
        print(f"    - Matched Employee ID: {data_submit.get('resolved_employee_id')}")
        print(f"    - Matched Employee Name: {data_submit.get('resolved_employee_name')}")
        print(f"    - Elo Delta: {data_submit.get('elo_delta')}")
        assert data_submit.get("success") is True or data_submit.get("status") == "success"
        assert data_submit.get("resolved_employee_id") == str(employee.id)
        assert data_submit.get("elo_delta") == -25
        assert "/training/" in (data_submit.get("redirect_url") or "")

        # 6. Live Radar Polling Check (After form submission):
        res_radar_2 = await client.get(f"/api/v1/campaigns/{campaign_id}/scans", headers=auth_headers)
        assert res_radar_2.status_code == 200
        scans_2 = res_radar_2.json()
        print(f"\n[6] Live Radar Polling Check (After form submission):")
        print(f"    - Scans Count: {len(scans_2)}")
        assert len(scans_2) >= 1
        s2 = scans_2[0]
        print(f"    - Scan ID: {s2['id']}")
        print(f"    - Event Type: {s2.get('event_type')}")
        print(f"    - Exact Device Model: {s2.get('device_model')}")
        print(f"    - City & Country: {s2.get('city')}, {s2.get('country')}")
        print(f"    - ISP: {s2.get('isp')}")
        print(f"    - IP Address: {s2.get('ip_address')}")
        print(f"    - Submitted Username: {s2.get('username') or s2.get('username_entered')}")
        print(f"    - Submitted Email: {s2.get('email') or s2.get('email_entered')}")
        print(f"    - Password Submitted Flag: {s2.get('password_submitted')}")
        print(f"    - Matched Employee: {s2.get('employee_name')} (ID: {s2.get('employee_id')})")
        assert s2.get("device_model") == "Samsung Galaxy S23"
        assert s2.get("city") == "Sanaa"
        assert s2.get("country") == "Yemen"
        assert "YemenNet" in (s2.get("isp") or "")
        assert s2.get("ip_address") == "175.110.45.10"
        assert s2.get("email") == employee.email
        assert s2.get("password_submitted") is True
        assert s2.get("employee_id") == str(employee.id)

    # 7. Verify Database State
    async with session_factory() as db:
        scan_db = (await db.execute(select(QRScan).where(QRScan.campaign_id == campaign_id))).scalars().first()
        tracking_db = (await db.execute(select(EmailTracking).where(EmailTracking.campaign_id == campaign_id))).scalars().first()
        emp_db = await db.get(HumanAsset, employee.id)

        print(f"\n[7] Database State Verification:")
        print(f"    A. `qr_scans` table row:")
        print(f"       - ID: {scan_db.id}")
        print(f"       - Device Model: {scan_db.device_model}")
        print(f"       - City & Country: {scan_db.city}, {scan_db.country}")
        print(f"       - ISP: {scan_db.isp}")
        print(f"       - IP: {scan_db.ip_address}")
        print(f"       - Username: {scan_db.username}")
        print(f"       - Email: {scan_db.email}")
        print(f"       - Password Submitted: {scan_db.password_submitted}")
        print(f"    B. `tracking_events` table row:")
        print(f"       - ID: {tracking_db.id}")
        print(f"       - Last IP: {tracking_db.last_ip_address}")
        print(f"       - Submitted Username: {tracking_db.submitted_username}")
        print(f"       - Submitted Email: {tracking_db.submitted_email}")
        print(f"       - Client Context: {json.dumps(tracking_db.client_context, ensure_ascii=False)}")
        print(f"    C. `human_assets` Employee Elo:")
        print(f"       - Score: {initial_elo} -> {emp_db.elo_score} (-25 penalty applied)")

        assert scan_db.device_model == "Samsung Galaxy S23"
        assert scan_db.city == "Sanaa"
        assert scan_db.country == "Yemen"
        assert "YemenNet" in scan_db.isp
        assert scan_db.ip_address == "175.110.45.10"
        assert scan_db.email == employee.email
        assert scan_db.password_submitted is True
        assert tracking_db.submitted_email == employee.email
        assert tracking_db.client_context.get("device_model") == "Samsung Galaxy S23"
        assert tracking_db.client_context.get("city") == "Sanaa"
        assert emp_db.elo_score == initial_elo - 25

    print("\n" + "=" * 75)
    print("STABILIZED QR CHANNEL PIPELINE FULLY VERIFIED WITH 100% SUCCESS!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
