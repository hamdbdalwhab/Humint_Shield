import asyncio
import json
import uuid
import httpx
from sqlalchemy import select
from app.database import get_session_factory
from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset, Organization, QRScan, User
from app.security import create_access_token

async def run_live_e2e():
    print("=" * 60)
    print("STARTING REAL END-TO-END VERIFICATION OF QR CHANNEL")
    print("=" * 60)

    session_factory = get_session_factory()

    async with session_factory() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        template = (await db.execute(select(EmailTemplate))).scalars().first()
        employee = (await db.execute(select(HumanAsset).order_by(HumanAsset.created_at.desc()))).scalars().first()
        user = (await db.execute(select(User).where(User.organization_id == org.id))).scalars().first()

        initial_elo = employee.elo_score
        print(f"[1] Target Test Employee: {employee.first_name} {employee.last_name} ({employee.email})")
        print(f"    Initial Elo Score: {initial_elo}")
        print(f"    Admin User: {user.email} (Role: {user.role})")

        campaign = EmailCampaign(
            organization_id=org.id,
            template_id=template.id,
            name=f"E2E QR Generic Test {uuid.uuid4().hex[:6]}",
            status="active",
            channel="qr",
            channel_config={
                "qr": {
                    "lure_type": "bonus",
                    "pretext_key": "bonus",
                    "branding": {
                        "company_name": "Humint Security Corp",
                        "label": "Internal Benefit",
                    }
                }
            },
            target_employee_ids=[],
            total_targets=0,
            sent_count=0,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        campaign_id = campaign.id
        print(f"[2] Created Generic QR Campaign: ID={campaign_id}, Name='{campaign.name}', channel='{campaign.channel}'")

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # --- TEST 1: MATCHED EMPLOYEE FLOW ---
        scan_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
            "X-Forwarded-For": "102.156.40.12",
        }
        print(f"\n[3] Triggering Scan: GET /api/v1/track/qr/{campaign_id}")
        scan_resp = await client.get(f"/api/v1/track/qr/{campaign_id}", headers=scan_headers, follow_redirects=False)
        print(f"    Response Status: {scan_resp.status_code}")
        print(f"    Redirect Location: {scan_resp.headers.get('location')}")
        assert scan_resp.status_code == 302
        assert f"/qr/landing/{campaign_id}" in scan_resp.headers.get("location")

        async with session_factory() as db:
            tracking_row = (
                await db.execute(
                    select(EmailTracking).where(
                        EmailTracking.campaign_id == campaign_id,
                        EmailTracking.channel == "qr"
                    )
                )
            ).scalars().first()
            assert tracking_row is not None
            print(f"    tracking_events row: ID={tracking_row.id}, UUID={tracking_row.tracking_uuid}, event_type='{tracking_row.event_type}', ip='{tracking_row.last_ip_address}'")
            assert tracking_row.event_type == "qr_scanned"
            assert tracking_row.last_ip_address == "102.156.40.12"

            qr_scan_row = (
                await db.execute(
                    select(QRScan).where(QRScan.campaign_id == campaign_id)
                )
            ).scalars().first()
            assert qr_scan_row is not None
            print(f"    qr_scans row: ID={qr_scan_row.id}, event_type='{qr_scan_row.event_type}', user_agent={qr_scan_row.user_agent}")
            assert qr_scan_row.event_type == "qr_scanned"

        fingerprint = {
            "screen": "393x852",
            "viewport": "393x740",
            "canvas_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "device_hash": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
            "timezone": "Asia/Riyadh",
            "platform": "iPhone",
        }
        submit_payload = {
            "campaign_id": str(campaign_id),
            "tracking_uuid": str(tracking_row.tracking_uuid),
            "email": employee.email,
            "username": employee.email.split("@")[0],
            "password_submitted": True,
            "fingerprint_data": fingerprint,
        }
        print(f"\n[4] Submitting Credential Form (Matched): POST /api/v1/track/qr/submit")
        submit_resp = await client.post(
            "/api/v1/track/qr/submit",
            json=submit_payload,
            headers={"X-Forwarded-For": "102.156.40.12", "User-Agent": scan_headers["User-Agent"]}
        )
        print(f"    Response Status: {submit_resp.status_code}")
        print(f"    Response JSON: {submit_resp.json()}")
        assert submit_resp.status_code == 200
        assert submit_resp.json().get("status") == "success"

        async with session_factory() as db:
            emp_after = await db.get(HumanAsset, employee.id)
            new_elo = emp_after.elo_score
            print(f"\n[5] Post-Submission Verification (Matched):")
            print(f"    Employee Elo Before: {initial_elo} -> After: {new_elo} (Diff: {new_elo - initial_elo})")
            assert new_elo == initial_elo - 25

            updated_tracking = (
                await db.execute(
                    select(EmailTracking).where(
                        EmailTracking.campaign_id == campaign_id,
                        EmailTracking.channel == "qr"
                    )
                )
            ).scalars().first()
            assert updated_tracking.event_type == "qr_credential_submitted"
            assert updated_tracking.employee_id == employee.id

            updated_qr_scan = (
                await db.execute(
                    select(QRScan).where(QRScan.campaign_id == campaign_id)
                )
            ).scalars().first()
            assert updated_qr_scan.event_type == "qr_credential_submitted"
            assert updated_qr_scan.employee_id == employee.id

        # --- TEST 2: UNMATCHED (UNKNOWN EMPLOYEE) FLOW ---
        print(f"\n[6] Submitting Credential Form (Unmatched / Unknown): POST /api/v1/track/qr/submit")
        unmatched_payload = {
            "campaign_id": str(campaign_id),
            "email": "external.attacker.unknown@notcompany.com",
            "username": "unknown_intruder",
            "password_submitted": True,
            "fingerprint_data": {
                "screen": "1920x1080",
                "device_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                "platform": "Linux",
            },
        }
        unmatched_resp = await client.post(
            "/api/v1/track/qr/submit",
            json=unmatched_payload,
            headers={"X-Forwarded-For": "89.200.15.4", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        )
        print(f"    Unmatched Status: {unmatched_resp.status_code}")
        print(f"    Unmatched JSON: {unmatched_resp.json()}")
        assert unmatched_resp.status_code == 200
        assert unmatched_resp.json().get("unknown") is True
        assert unmatched_resp.json().get("identity_resolution") == "unknown"

        async with session_factory() as db:
            unknown_scan = (
                await db.execute(
                    select(QRScan).where(
                        QRScan.campaign_id == campaign_id,
                        QRScan.email == "external.attacker.unknown@notcompany.com"
                    )
                )
            ).scalars().first()
            assert unknown_scan is not None
            assert unknown_scan.employee_id is None
            assert unknown_scan.identity_resolution == "unknown"
            print(f"    Unknown Scan row in DB: ID={unknown_scan.id}, employee_id={unknown_scan.employee_id}, resolution='{unknown_scan.identity_resolution}'")

        # --- TEST 3: LIVE RADAR LISTING BOTH ---
        access_token = create_access_token(
            str(user.id),
            extra={"role": user.role, "org_id": str(user.organization_id)}
        )
        scans_resp = await client.get(
            f"/api/v1/campaigns/{campaign_id}/scans",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        print(f"\n[7] Live Radar Endpoint: GET /api/v1/campaigns/{campaign_id}/scans")
        print(f"    Status: {scans_resp.status_code}")
        raw_radar = scans_resp.json()
        radar_items = raw_radar if isinstance(raw_radar, list) else raw_radar.get("items", [])
        print(f"    Radar Items Count: {len(radar_items)}")
        assert len(radar_items) == 2
        for idx, item in enumerate(radar_items):
            print(f"    Radar Item [{idx+1}]:")
            print(f"      - Event Type: {item.get('event_type')}")
            print(f"      - Employee: {item.get('employee_name') or 'UNKNOWN'} (ID: {item.get('employee_id')})")
            print(f"      - Entered Email: {item.get('email_entered')}")
            print(f"      - Entered Username: {item.get('username_entered')}")
            print(f"      - Resolution: {item.get('identity_resolution')}")
            print(f"      - IP: {item.get('ip_address')}")

    print("\n" + "=" * 60)
    print("ALL REAL TESTS (MATCHED & UNMATCHED & RADAR) PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_live_e2e())
