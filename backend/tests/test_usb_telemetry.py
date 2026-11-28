"""USB document telemetry: an open must always reach the monitoring board.

The regression these tests pin down: a *generic* physical drop campaign has no
employee on its tracking row, and the interaction ledger used to reject a NULL
``employee_id``.  Every open then died in an ``IntegrityError`` rollback, so the
document was read, the redirect worked, and the live board stayed empty.
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTracking, TrainingInteraction
from app.services.usb_drop_service import (
    DEFAULT_DOCUMENT_NAME,
    HTML_DOCUMENT_NAME,
    IDENTITY_TOOL_CMD_NAME,
    IDENTITY_TOOL_PS1_NAME,
    USBDropRecipient,
    build_usb_html,
    build_usb_identity_tool,
    resolve_usb_copy,
)


async def _create_usb_campaign(
    client,
    auth_headers,
    organization,
    template,
    employee_ids: list[uuid.UUID],
) -> dict:
    """Create a USB campaign through the public API."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "USB Telemetry Campaign",
            "template_id": str(template.id),
            "channel": "usb",
            "channel_config": {"usb": {"document_name": "راتب_الشهر_القادم.pdf"}},
            "difficulty_level": 5,
            "target_employee_ids": [str(employee_id) for employee_id in employee_ids],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _generic_tracking_row(
    client, db: AsyncSession, auth_headers, organization, template
) -> tuple[EmailCampaign, EmailTracking]:
    """Create a generic USB campaign and materialise its tracking row."""
    created = await _create_usb_campaign(
        client, auth_headers, organization, template, []
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-html",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    campaign = await db.get(EmailCampaign, uuid.UUID(created["id"]))
    assert campaign is not None
    row = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().first()
    assert row is not None
    assert row.employee_id is None
    return campaign, row


def _telemetry_packet(tracking_uuid: str) -> dict:
    """A realistic packet as the HTML document sends it."""
    return {
        "schema": 2,
        "event": "usb_document_opened",
        "client_event_id": f"usb-{tracking_uuid[:8]}-1",
        "fingerprint": "deadbeef",
        "source": {
            "href": "file:///H:/%D8%A7%D9%84%D8%B1%D9%88%D8%A7%D8%AA%D8%A8_%D8%A7%D9%84%D8%B3%D8%B1%D9%8A%D8%A9.html",
            "path": "H:/الرواتب_السرية.html",
            "protocol": "file:",
            "opened_at": "2026-11-16T09:30:00.000Z",
        },
        "device": {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36",
            "ua_platform": "Windows",
            "ua_platform_version": "15.0.0",
            "ua_architecture": "x86",
            "ua_bitness": "64",
            "os": "Windows 10/11",
            "browser": "Chrome",
            "language": "ar",
            "timezone": "Asia/Aden",
            "hardware_concurrency": 8,
            "device_memory_gb": 8,
            "hostname": "FIN-PC-04",
            "username": "ahmed.finance",
            "domain": "CORP",
        },
        "screen": {"width": 1920, "height": 1080, "pixel_ratio": 1.25},
        "gpu": {"vendor": "Google Inc.", "renderer": "ANGLE (Intel UHD Graphics 620)"},
        "network": {"online": True, "effective_type": "4g", "downlink_mbps": 9.5, "rtt_ms": 75},
        "webrtc": {"local_ips": ["192.168.1.24"]},
        "battery": {"level": 0.82, "charging": True},
        "storage": {"quota_mb": 120000, "usage_mb": 240},
        "geolocation": {"latitude": 15.3694, "longitude": 44.191, "accuracy_m": 25},
    }


async def test_generic_usb_open_is_persisted_with_device_profile(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """A no-employee USB open is recorded instead of being rolled back."""
    campaign, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    packet = _telemetry_packet(str(row.tracking_uuid))

    response = await client.post(
        f"/api/v1/track/usb/{row.tracking_uuid}",
        content=json.dumps(packet, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "text/plain;charset=UTF-8"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["recorded"] is True
    assert response.headers["access-control-allow-origin"] == "*"

    await db.refresh(row)
    assert row.opened_at is not None
    assert row.last_ip_address is not None
    assert row.client_context is not None
    assert row.client_context["device_fingerprint"] == "deadbeef"
    assert row.client_context["source_path"] == "H:/الرواتب_السرية.html"
    assert row.client_context["geo"]["city"] or row.client_context["geo"] == {}
    stored = row.client_context["usb_telemetry"]
    assert stored["device"]["os"] == "Windows 10/11"
    assert stored["webrtc"]["local_ips"] == ["192.168.1.24"]
    assert stored["server"]["device_model"]

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type == "usb_opened",
            )
        )
    ).scalars().all()
    assert len(interactions) == 1
    details = interactions[0].details
    assert interactions[0].employee_id is None
    assert details["device"]["platform"] == "Windows"
    assert details["device"]["source_path"] == "H:/الرواتب_السرية.html"
    assert details["hostname"] == "FIN-PC-04"

    live = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}/live",
        headers=auth_headers,
    )
    assert live.status_code == 200, live.text
    board = live.json()
    recipient = board["recipients"][0]
    assert recipient["telemetry_received"] is True
    assert "Windows" in recipient["device_summary"]
    assert recipient["source_path"] == "H:/الرواتب_السرية.html"
    assert recipient["name"] == "FIN-PC-04"
    assert board["recent_events"][0]["label"] == "USB awareness document opened"


async def test_generic_usb_get_beacon_records_the_open(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """The plain GET beacon (image/QR fallback) also persists a generic open."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    response = await client.get(
        f"/api/v1/track/usb/{row.tracking_uuid}",
        headers={"user-agent": "USB-Fallback/1.0"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    await db.refresh(row)
    assert row.opened_at is not None

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id
            )
        )
    ).scalars().all()
    assert [item.event_type for item in interactions] == ["usb_opened"]


async def test_repeated_beacon_is_not_counted_twice(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """A client retry carries the same event id and stays one open."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    packet = _telemetry_packet(str(row.tracking_uuid))
    payload = json.dumps(packet).encode("utf-8")
    for _ in range(3):
        response = await client.post(
            f"/api/v1/track/usb/{row.tracking_uuid}", content=payload
        )
        assert response.status_code == 200

    await db.refresh(row)
    assert row.open_count == 1
    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id
            )
        )
    ).scalars().all()
    assert len(interactions) == 1


async def test_offline_queued_beacon_is_accepted_later(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """A packet captured offline is accepted unchanged once the host reconnects."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    packet = _telemetry_packet(str(row.tracking_uuid))
    packet["client_event_id"] = f"usb-{row.tracking_uuid}-offline"
    packet["network"] = {"online": False, "effective_type": None}
    packet["queue"] = {"offline_at_capture": True}

    response = await client.post(
        f"/api/v1/track/usb/{row.tracking_uuid}",
        content=json.dumps(packet).encode("utf-8"),
    )
    assert response.status_code == 200
    assert response.json()["recorded"] is True
    await db.refresh(row)
    stored = row.client_context["usb_telemetry"]
    assert stored["queue"]["offline_at_capture"] is True
    assert stored["network"]["online"] is False


async def test_smaller_follow_up_packet_keeps_the_richer_profile(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """A retry or an older document copy cannot erase a captured profile."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    rich = _telemetry_packet(str(row.tracking_uuid))
    rich["client_event_id"] = "usb-rich-1"
    assert (
        await client.post(
            f"/api/v1/track/usb/{row.tracking_uuid}",
            content=json.dumps(rich).encode(),
        )
    ).status_code == 200

    minimal = {
        "schema": 2,
        "event": "usb_document_opened",
        "client_event_id": "usb-minimal-1",
        "device": {"os": "Windows 10/11"},
        "network": {"online": True},
    }
    assert (
        await client.post(
            f"/api/v1/track/usb/{row.tracking_uuid}",
            content=json.dumps(minimal).encode(),
        )
    ).status_code == 200

    await db.refresh(row)
    stored = row.client_context["usb_telemetry"]
    assert stored["device"]["os"] == "Windows 10/11"
    assert stored["device"]["hardware_concurrency"] == 8
    assert stored["gpu"]["renderer"].startswith("ANGLE")
    assert stored["screen"]["width"] == 1920
    assert row.open_count == 2


async def test_unknown_or_invalid_tracking_id_is_harmless(client) -> None:
    """A deleted campaign must not turn the document into an error page."""
    response = await client.post(
        f"/api/v1/track/usb/{uuid.uuid4()}", content=b'{"event": "usb_document_opened"}'
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False

    invalid = await client.post("/api/v1/track/usb/not-a-uuid", content=b"{}")
    assert invalid.status_code == 200
    assert invalid.json()["ok"] is False


async def test_training_page_visit_is_recorded_for_a_generic_row(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """Following the warning's training link must show up on the board."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    response = await client.post(f"/api/v1/track/form-view/{row.tracking_uuid}")
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True

    await db.refresh(row)
    assert row.viewed_at is not None
    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id
            )
        )
    ).scalars().all()
    assert [item.event_type for item in events] == ["form_viewed"]
    assert events[0].employee_id is None


async def test_recipient_dossier_works_for_a_generic_row(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """Opening the recipient details of an endpoint row must not return a 500."""
    campaign, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    await client.post(
        f"/api/v1/track/usb/{row.tracking_uuid}",
        content=json.dumps(_telemetry_packet(str(row.tracking_uuid))).encode(),
    )
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}"
        f"/recipients/{row.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["employee"]["department"] == "Physical USB drop"
    assert payload["employee"]["is_blacklisted"] is False
    assert payload["record"]["opened_at"] is not None


def test_document_names_follow_the_campaign_template() -> None:
    """A password campaign must not drop a salary statement."""
    copy = resolve_usb_copy(
        {"usb": {}},
        template_name="Urgent Password Change",
        template_subject="Reset your password today",
    )
    assert copy.document_name == "تحديث_كلمة_المرور.pdf"
    assert copy.html_document_name == "تحديث_كلمة_المرور.html"

    invoice = resolve_usb_copy(
        None, template_name="Invoice overdue", template_subject=""
    )
    assert invoice.document_name == "فاتورة_مستحقة.pdf"

    # An explicit operator name always wins, even over the template rule.
    explicit = resolve_usb_copy(
        {"usb": {"document_name": "custom.pdf"}},
        template_name="Urgent Password Change",
    )
    assert explicit.document_name == "custom.pdf"
    assert explicit.html_document_name == "custom.html"

    # A legacy campaign that stored the old default name is not an override: the
    # template rule must still win.
    legacy = resolve_usb_copy(
        {"usb": {"document_name": DEFAULT_DOCUMENT_NAME}},
        template_name="Urgent Password Change",
    )
    assert legacy.document_name == "تحديث_كلمة_المرور.pdf"
    assert legacy.html_document_name == "تحديث_كلمة_المرور.html"

    # No template at all keeps the historical salary defaults.
    default = resolve_usb_copy(None)
    assert default.document_name == DEFAULT_DOCUMENT_NAME
    assert default.html_document_name == HTML_DOCUMENT_NAME


def test_html_document_reports_rich_telemetry_and_queues_offline() -> None:
    """The generated document collects the profile and survives an offline open."""

    class _Org:
        name = "Acme"
        brand_primary_color = "#0E7490"
        brand_logo_data = None

    recipient = USBDropRecipient(
        name="Ahmed",
        email="ahmed@acme.example",
        tracking_uuid=str(uuid.uuid4()),
        tracking_url="https://example.test/api/v1/track/usb/abc",
    )
    document = build_usb_html(
        organization=_Org(),
        recipient=recipient,
        training_url="https://example.test/training/abc?channel=usb",
        support_email="security@acme.example",
    ).decode("utf-8")

    for marker in (
        "humint_usb_queue_v2",
        'addEventListener("online"',
        "sendBeacon",
        "navigator.geolocation",
        "ua_platform",
        "hardware_concurrency",
        "device_memory_gb",
        "effectiveType",
        "local_ips",
        "WEBGL_debug_renderer_info",
        "report-state",
        "usb_document_opened",
    ):
        assert marker in document, marker
    # The beacon must stay a simple, cache-busting POST from file://.
    assert 'mode: "no-cors"' in document
    assert "fetch(trackingUrl" in document
    assert 'method: "POST"' in document
    # Still inert: no form, no input, no secret collection.
    assert "<form" not in document.lower()
    assert "<input" not in document.lower()
    assert "document.cookie" not in document


def test_forensic_context_is_flat_for_the_dossier() -> None:
    """A stored USB packet must render as real values, never a wall of dashes.

    The regression: the dossier read ``client_context.device_real_name`` while
    the packet lived under ``client_context.usb_telemetry.device``, so a fully
    captured machine was displayed as "—".
    """
    from types import SimpleNamespace

    from app.services.interaction_report import build_forensic_context

    tracking = SimpleNamespace(
        client_context={
            "usb_event_ids": ["usb-1"],
            "device_fingerprint": "f190c2f3",
            "geo": {"city": "Sanaa", "country": "Yemen", "isp": "YemenNet"},
            "usb_telemetry": {
                "schema": 2,
                "fingerprint": "f190c2f3",
                "source": {"path": "H:/تحديث_كلمة_المرور.html", "opened_at": "2026-11-16T02:18:52Z"},
                "device": {
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:160.0) Gecko/20100101 Firefox/160.0",
                    "os": "Windows 10/11",
                    "browser": "Firefox",
                    "language": "ar",
                    "timezone": "Asia/Riyadh",
                    "hardware_concurrency": 4,
                    "device_memory_gb": 8,
                },
                "screen": {"width": 1366, "height": 768, "pixel_ratio": 1},
                "gpu": {"renderer": "ANGLE (Intel, Intel(R) HD Graphics 400)"},
                "webrtc": {
                    "local_ips": ["cd2f9dc5-cadb-4f16-9fb0-ff1705e89169.local", "192.168.1.7"]
                },
                "server": {
                    "ip": "176.123.31.154",
                    "city": "Sanaa",
                    "country": "Yemen",
                    "isp": "YemenNet",
                    "device_model": "Windows PC",
                },
            },
        },
        open_count=2,
        last_ip_address="176.123.31.154",
        last_user_agent="Mozilla/5.0",
    )

    context = build_forensic_context(tracking)

    assert context is not None
    assert context["cpu_cores"] == 4
    assert context["device_memory_gb"] == 8
    assert context["screen_resolution"] == "1366x768"
    assert context["pixel_ratio"] == 1
    assert context["language"] == "ar"
    assert context["os"] == "Windows 10/11"
    assert context["browser"] == "Firefox"
    assert context["gpu_renderer"].startswith("ANGLE")
    assert context["local_ip"] == "192.168.1.7"
    assert context["mDNS_name"].endswith(".local")
    assert context["isp"] == "YemenNet"
    assert context["city"] == "Sanaa"
    assert context["country"] == "Yemen"
    assert context["hardware_fingerprint"] == "f190c2f3"
    assert context["source_path"].endswith(".html")
    assert context["scan_count"] == 2
    assert context["status"] == "repeat_scan"
    assert context["telemetry_received"] is True
    # The raw packet is still available to the debug footer.
    assert context["usb_telemetry"]["device"]["hardware_concurrency"] == 4


def test_forensic_context_is_none_without_client_context() -> None:
    from types import SimpleNamespace

    from app.services.interaction_report import build_forensic_context

    assert build_forensic_context(SimpleNamespace(client_context=None)) is None


#: What the optional local collector posts once it has run on the target machine.
def _identity_probe_packet(event_id: str = "probe-1") -> dict:
    return {
        "source": "local_tool",
        "client_event_id": event_id,
        "collected_at": "2026-11-16T09:32:10.0000000Z",
        "username": "ahmed.finance",
        "user_domain": "CORP",
        "logged_on_user": "CORP\\ahmed.finance",
        "hostname": "FIN-PC-04",
        "domain": "corp.local",
        "workgroup": None,
        "os_caption": "Microsoft Windows 11 Pro",
        "os_version": "10.0.22631",
        "os_build": "22631",
        "os_arch": "64-bit",
        "manufacturer": "Dell Inc.",
        "model": "Latitude 5440",
        "serial": "7XK2Q53",
        "cpu": "12th Gen Intel(R) Core(TM) i5-1245U",
        "cpu_cores": 10,
        "cpu_logical": 12,
        "ram_gb": 16.0,
        "local_ip": "10.20.4.31",
        "mac": "A4:BB:6D:11:22:33",
        "gateway": "10.20.4.1",
        "dns_servers": "10.20.0.10, 10.20.0.11",
        "session_name": "Console",
        "powershell": "5.1.22621.4249",
        "timezone": "Arab Standard Time",
        "uptime_minutes": 4321.0,
        "is_admin": False,
        "unknown_field": "must be dropped",
    }


def test_identity_tool_is_optional_and_reports_only_identity() -> None:
    """The collector names the account and machine and does nothing else."""
    recipient = USBDropRecipient(
        name="Ahmed",
        email="ahmed@acme.example",
        tracking_uuid="715cd711-650d-4888-9652-dd022297ea68",
        tracking_url="https://api.example.test/api/v1/track/usb/715cd711",
    )
    files = dict(
        build_usb_identity_tool(recipient=recipient, base_url="https://api.example.test/")
    )
    assert set(files) == {IDENTITY_TOOL_CMD_NAME, IDENTITY_TOOL_PS1_NAME}

    script = files[IDENTITY_TOOL_PS1_NAME].decode("utf-8-sig")
    assert (
        "https://api.example.test/api/v1/track/usb/"
        "715cd711-650d-4888-9652-dd022297ea68/device"
    ) in script
    assert "$env:USERNAME" in script
    assert "$env:COMPUTERNAME" in script
    assert "Invoke-RestMethod" in script
    assert "humint_usb_identity_queue.json" in script
    assert "Win32_ComputerSystem" in script
    # Identity only: no user files are read, nothing on the machine is changed.
    for forbidden in (
        "Set-ItemProperty",
        "Remove-Item -Recurse",
        "Start-Process",
        "$env:USERPROFILE",
        "document.cookie",
    ):
        assert forbidden not in script, forbidden

    launcher = files[IDENTITY_TOOL_CMD_NAME].decode("ascii")
    assert IDENTITY_TOOL_PS1_NAME in launcher
    assert "-ExecutionPolicy Bypass" in launcher
    assert "\r\n" in launcher


async def test_local_identity_probe_enriches_the_dossier(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """After the tool runs, the details window shows the Windows account and host."""
    campaign, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    assert (
        await client.post(
            f"/api/v1/track/usb/{row.tracking_uuid}",
            content=json.dumps(_telemetry_packet(str(row.tracking_uuid))).encode(),
        )
    ).status_code == 200

    response = await client.post(
        f"/api/v1/track/usb/{row.tracking_uuid}/device",
        json=_identity_probe_packet(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["recorded"] is True
    assert response.headers["access-control-allow-origin"] == "*"

    await db.refresh(row)
    stored = row.client_context["usb_telemetry"]["local_probe"]
    assert stored["source"] == "local_tool"
    assert stored["identity"]["username"] == "ahmed.finance"
    assert stored["identity"]["hostname"] == "FIN-PC-04"
    assert "unknown_field" not in stored["identity"]
    # Enrichment only: the open itself is not counted or scored again.
    assert row.open_count == 1
    assert row.client_context["identity_source"] == "local_tool"

    events = (
        await db.execute(
            select(TrainingInteraction).where(TrainingInteraction.tracking_id == row.id)
        )
    ).scalars().all()
    assert [item.event_type for item in events] == ["usb_opened", "usb_device_probe"]
    assert events[1].details["hostname"] == "FIN-PC-04"

    dossier = await client.get(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign.id}"
        f"/recipients/{row.id}",
        headers=auth_headers,
    )
    assert dossier.status_code == 200, dossier.text
    record = dossier.json()["record"]
    context = record["client_context"]
    assert context["username"] == "ahmed.finance"
    assert context["device_real_name"] == "FIN-PC-04"
    assert context["windows_account"] == "ahmed.finance"
    assert context["windows_hostname"] == "FIN-PC-04"
    assert context["windows_logged_on_user"] == "CORP\\ahmed.finance"
    assert context["device_domain"] == "corp.local"
    assert context["device_serial"] == "7XK2Q53"
    assert context["os_build"] == "22631"
    assert context["device_model"] == "Latitude 5440"
    assert context["cpu_cores"] == 10
    assert context["device_memory_gb"] == 16.0
    assert context["identity_source"] == "local_tool"
    # The browser profile is still there for the rest of the card.
    assert context["gpu_renderer"].startswith("ANGLE")


async def test_repeated_identity_probe_is_ignored(
    client, db: AsyncSession, auth_headers, organization, custom_template
) -> None:
    """A retried collector run is one identity record, not two."""
    _, row = await _generic_tracking_row(
        client, db, auth_headers, organization, custom_template
    )
    payload = _identity_probe_packet("probe-retry")
    for _ in range(2):
        response = await client.post(
            f"/api/v1/track/usb/{row.tracking_uuid}/device", json=payload
        )
        assert response.status_code == 200

    assert response.json()["recorded"] is False
    assert response.json()["duplicate"] is True
    events = (
        await db.execute(
            select(TrainingInteraction).where(TrainingInteraction.tracking_id == row.id)
        )
    ).scalars().all()
    assert [item.event_type for item in events] == ["usb_device_probe"]


async def test_identity_probe_rejects_unknown_and_invalid_rows(client) -> None:
    """The public endpoint never turns a bad identifier into a 500."""
    unknown = await client.post(
        f"/api/v1/track/usb/{uuid.uuid4()}/device", json=_identity_probe_packet()
    )
    assert unknown.status_code == 200
    assert unknown.json()["ok"] is False

    invalid = await client.post(
        "/api/v1/track/usb/not-a-uuid/device", json=_identity_probe_packet()
    )
    assert invalid.status_code == 200
    assert invalid.json()["reason"] == "invalid_tracking_id"

    empty = await client.post(
        f"/api/v1/track/usb/{uuid.uuid4()}/device", content=b"not json"
    )
    assert empty.status_code == 200
    assert empty.json()["ok"] is False


def test_forensic_context_prefers_the_local_probe() -> None:
    """The mDNS placeholder never overrides the name the collector read."""
    from types import SimpleNamespace

    from app.services.interaction_report import build_forensic_context

    tracking = SimpleNamespace(
        client_context={
            "usb_telemetry": {
                "device": {
                    "os": "Windows 10/11",
                    "hostname": "cd2f9dc5-cadb-4f16-9fb0-ff1705e89169.local",
                    "username": None,
                },
                "webrtc": {
                    "local_ips": ["cd2f9dc5-cadb-4f16-9fb0-ff1705e89169.local"]
                },
                "local_probe": {
                    "source": "local_tool",
                    "identity": {
                        "username": "ahmed.finance",
                        "hostname": "FIN-PC-04",
                        "domain": "corp.local",
                        "model": "Latitude 5440",
                        "serial": "7XK2Q53",
                        "os_build": "22631",
                        "is_admin": False,
                    },
                    "received_at": "2026-11-16T09:32:11+00:00",
                },
            }
        },
        open_count=1,
        last_ip_address="10.20.4.31",
        last_user_agent="HUMINT-Identity-Tool/1.0 WindowsPowerShell/5.1",
    )

    context = build_forensic_context(tracking)

    assert context is not None
    assert context["identity_source"] == "local_tool"
    assert context["device_real_name"] == "FIN-PC-04"
    assert context["hostname"] == "FIN-PC-04"
    assert context["username"] == "ahmed.finance"
    assert context["mDNS_name"].endswith(".local")
    assert context["device_model"] == "Latitude 5440"
    assert context["probe_elevated"] is False
    assert context["local_probe"]["identity"]["hostname"] == "FIN-PC-04"
