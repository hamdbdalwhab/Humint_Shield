"""Real-Time QR Telemetry, WebSocket, Deep Device Identification, GeoIP & Timeline Test."""
from __future__ import annotations

import asyncio
import json
import uuid
import httpx
import websockets
from sqlalchemy import select

from app.database import get_session_factory
from app.models import EmailCampaign, EmailTemplate, HumanAsset, Organization, QRScan


async def run_telemetry_verification():
    print("=" * 70)
    print("STARTING REAL-TIME QR TELEMETRY & DEEP DEVICE VERIFICATION")
    print("=" * 70)

    session_factory = get_session_factory()
    async with session_factory() as db:
        org = (await db.execute(select(Organization))).scalars().first()
        template = (await db.execute(select(EmailTemplate))).scalars().first()
        employee = (await db.execute(select(HumanAsset).order_by(HumanAsset.created_at.desc()))).scalars().first()

        assert org and template and employee, "Database must have org, template, and employee"
        initial_elo = employee.elo_score

        # 1. Create a generic QR campaign
        campaign = EmailCampaign(
            organization_id=org.id,
            template_id=template.id,
            name=f"Realtime Telemetry Test {uuid.uuid4().hex[:6]}",
            status="active",
            channel="qr",
            channel_config={"qr": {"lure_type": "bonus", "pretext_key": "bonus"}},
            target_employee_ids=[],
            total_targets=0,
            sent_count=0,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        campaign_id = campaign.id
        print(f"[1] Campaign Created: ID={campaign_id}, Name='{campaign.name}'")
        print(f"    Target Employee: {employee.first_name} {employee.last_name} ({employee.email}) | Elo: {initial_elo}")

    ws_uri = f"ws://127.0.0.1:8000/ws/campaign/{campaign_id}/scans"

    # 2. Connect Admin Dashboard WebSocket listener
    print(f"\n[2] Connecting Admin Live Radar WebSocket: {ws_uri}")
    async with websockets.connect(ws_uri) as admin_ws:
        print("    Admin Radar WebSocket: CONNECTED (Listening for real-time telemetry...)")

        # 3. Connect Mobile Visitor WebSocket (Simulating Samsung Galaxy S23 Ultra in Sana'a)
        mobile_ua = "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36"
        mobile_headers = [
            ("User-Agent", mobile_ua),
            ("X-Forwarded-For", "175.110.45.10"),  # Simulated Public IP
        ]
        print(f"\n[3] Mobile Phone (Samsung S23 Ultra) Scanning QR & Connecting WebSocket...")
        async with websockets.connect(ws_uri, additional_headers=mobile_headers) as mobile_ws:
            print("    Mobile Phone WebSocket: CONNECTED")

            # --- UPGRADE 1 & 2 & 3: Send page_viewed with fingerprint & GPS ---
            page_view_payload = {
                "event": "page_viewed",
                "campaign_id": str(campaign_id),
                "fingerprint": {
                    "screen": "393x852",
                    "device_model": "SM-S918B",
                    "webgl_renderer": "Adreno (TM) 740",
                    "platform": "Linux armv8l",
                    "fingerprint_hash": "a9b8c7d6e5f41234567890abcdef1234567890abcdef1234567890abcdef",
                    "device_hash": "d1e2f3a4b5c67890123456789abcdef0123456789abcdef0123456789abcdef0",
                },
                "gps": {
                    "latitude": 15.3694,
                    "longitude": 44.1910,
                },
            }
            print(f"    Sending Event: 'page_viewed' from mobile phone...")
            await mobile_ws.send(json.dumps(page_view_payload))

            # Admin Radar receives immediate broadcast
            admin_msg_1 = await asyncio.wait_for(admin_ws.recv(), timeout=5.0)
            data_1 = json.loads(admin_msg_1)
            print(f"\n[4] Admin Radar INSTANTLY RECEIVED Live Card Update (page_viewed):")
            print(f"    - Event Type: {data_1.get('event_type')}")
            print(f"    - Exact Device Model: {data_1.get('device_model')}")
            print(f"    - Geo Location: {data_1.get('city')}, {data_1.get('country')} (ISP: {data_1.get('isp')})")
            print(f"    - Public IP: {data_1.get('ip_address')}")
            print(f"    - Timeline Events: {len(data_1.get('real_time_events', []))} events")
            for ev in data_1.get('real_time_events', []):
                print(f"        * {ev.get('event')}: {ev.get('label')} at {ev.get('time_str')}")

            assert data_1.get("device_model") == "Samsung Galaxy S23 Ultra", f"Expected 'Samsung Galaxy S23 Ultra', got {data_1.get('device_model')}"
            assert data_1.get("city") == "Sanaa", f"Expected 'Sanaa', got {data_1.get('city')}"
            assert data_1.get("country") == "Yemen"
            assert "YemenNet" in (data_1.get("isp") or "")

            # --- UPGRADE 4: Send field_focused (email) ---
            await asyncio.sleep(0.5)
            focus_payload = {
                "event": "field_focused",
                "field": "email",
                "campaign_id": str(campaign_id),
            }
            print(f"\n[5] User on Mobile clicks Email Input -> Sending Event: 'field_focused'...")
            await mobile_ws.send(json.dumps(focus_payload))

            admin_msg_2 = await asyncio.wait_for(admin_ws.recv(), timeout=5.0)
            data_2 = json.loads(admin_msg_2)
            print(f"    Admin Radar INSTANTLY RECEIVED Timeline Update (field_focused):")
            print(f"    - Timeline Count: {len(data_2.get('real_time_events', []))} events")
            last_ev = data_2.get("real_time_events", [])[-1]
            print(f"    - Latest Timeline Action: {last_ev.get('event')} - {last_ev.get('label')} at {last_ev.get('time_str')}")
            assert last_ev.get("event") == "field_focused"

            # --- UPGRADE 1 & 4: Submit Credentials & Match Elo ---
            await asyncio.sleep(0.5)
            submit_payload = {
                "campaign_id": str(campaign_id),
                "email": employee.email,
                "username": employee.email.split("@")[0],
                "password_submitted": True,
                "fingerprint_data": page_view_payload["fingerprint"],
            }
            print(f"\n[6] User Submits Form -> POST /api/v1/track/qr/submit...")
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as http_client:
                resp = await http_client.post(
                    "/api/v1/track/qr/submit",
                    json=submit_payload,
                    headers={"X-Forwarded-For": "175.110.45.10", "User-Agent": mobile_ua}
                )
                print(f"    HTTP Submit Response: {resp.status_code}")
                assert resp.status_code == 200

            # Admin Radar receives broadcast from submission
            admin_msg_3 = await asyncio.wait_for(admin_ws.recv(), timeout=5.0)
            data_3 = json.loads(admin_msg_3)
            print(f"\n[7] Admin Radar INSTANTLY RECEIVED Submission Broadcast:")
            print(f"    - Event Type: {data_3.get('event_type')}")
            print(f"    - Matched Employee: {data_3.get('employee_name')} (ID: {data_3.get('employee_id')})")
            print(f"    - Elo Delta: {data_3.get('elo_delta')}")
            print(f"    - Time on Page: {data_3.get('time_on_page_seconds')} seconds")
            print(f"    - Full Timeline:")
            for ev in data_3.get('real_time_events', []):
                print(f"        * {ev.get('time_str')} - {ev.get('label')}")

            assert data_3.get("event_type") == "qr_credential_submitted"
            assert data_3.get("employee_id") == str(employee.id)
            assert data_3.get("employee_name") == f"{employee.first_name} {employee.last_name}"

        # 8. Check Database state directly
        async with session_factory() as db:
            scan_in_db = (
                await db.execute(select(QRScan).where(QRScan.campaign_id == campaign_id))
            ).scalars().first()
            emp_in_db = await db.get(HumanAsset, employee.id)

            print(f"\n[8] Database State Verification (qr_scans table):")
            print(f"    - ID: {scan_in_db.id}")
            print(f"    - Device Model Column: '{scan_in_db.device_model}'")
            print(f"    - Country Column: '{scan_in_db.country}'")
            print(f"    - City Column: '{scan_in_db.city}'")
            print(f"    - ISP Column: '{scan_in_db.isp}'")
            print(f"    - Latitude / Longitude: {scan_in_db.latitude}, {scan_in_db.longitude}")
            print(f"    - Real Time Events Column (JSON): {json.dumps(scan_in_db.real_time_events, ensure_ascii=False)}")
            print(f"    - Employee Elo Score: {initial_elo} -> {emp_in_db.elo_score} (-25 penalty applied)")

            assert scan_in_db.device_model == "Samsung Galaxy S23 Ultra"
            assert scan_in_db.city == "Sanaa"
            assert scan_in_db.country == "Yemen"
            assert "YemenNet" in scan_in_db.isp
            assert len(scan_in_db.real_time_events) >= 3
            assert emp_in_db.elo_score == initial_elo - 25

    print("\n" + "=" * 70)
    print("ALL 4 UPGRADES VERIFIED END-TO-END WITH ZERO ERRORS!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_telemetry_verification())
