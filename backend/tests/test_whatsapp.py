"""WhatsApp (WA-AKG) delivery, webhook scoring and click tracking.

Everything here runs offline: the HTTP layer uses ``httpx.MockTransport``, so no
test needs a real WhatsApp session, a QR scan or a live phone.  The tests pin
the documented WA-AKG contract (``/messages/{session}/{jid}/send`` with a Bearer
token), the 10-30 second anti-ban pacing, the webhook event mapping and the
Elo outcome of a reply.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    TrainingInteraction,
)
from app.services.campaign_launcher import CampaignLauncher
from app.services.template_personalizer import TemplatePersonalizer
from app.services.tracking_service import (
    EVENT_WHATSAPP_CLICKED,
    EVENT_WHATSAPP_READ,
    EVENT_WHATSAPP_REPLIED,
    classify_whatsapp_reply,
)
from app.services.whatsapp_service import (
    WhatsAppService,
    format_jid,
    inject_tracking_link,
    is_whatsapp_phone,
)

SESSION = "sess_test_1"
API_KEY = "wa_test_key"


def _settings(**overrides: object) -> Settings:
    """Return deterministic settings with a complete fake WA-AKG setup."""
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "base_url": "http://testserver",
        "wa_akg_api_url": "http://wa.test/api",
        "wa_akg_api_key": API_KEY,
        "wa_akg_session_id": SESSION,
        "wa_akg_min_delay_seconds": 10,
        "wa_akg_max_delay_seconds": 30,
        "wa_akg_webhook_secret": "",
        "short_link_provider": "none",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code, content=json.dumps(payload).encode(), headers={"content-type": "application/json"}
    )


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("phone", "expected"),
    [
        ("+967770447622", "967770447622@s.whatsapp.net"),
        ("967 770 447 622", "967770447622@s.whatsapp.net"),
    ],
)
def test_jid_format(phone: str, expected: str) -> None:
    assert format_jid(phone) == expected


@pytest.mark.parametrize("phone", ["", "123", "0770447622", None])
def test_invalid_phone_is_rejected(phone) -> None:
    assert is_whatsapp_phone(phone) is False


def test_tracking_link_replaces_the_placeholder() -> None:
    uid = uuid.uuid4()
    body = inject_tracking_link("Your VPN expired: {{link}}", uid)
    assert body == f"Your VPN expired: http://testserver/api/v1/track/whatsapp/{uid}"


def test_tracking_link_is_appended_when_missing() -> None:
    uid = uuid.uuid4()
    assert str(uid) in inject_tracking_link("Verify your session", uid)


@pytest.mark.parametrize(
    ("text", "category", "delta"),
    [
        ("The code is 4821", "disclosed", -15),
        ("sure, password is Summer2026", "disclosed", -15),
        ("This looks like phishing, I am reporting it", "suspicious", 10),
        ("Thanks, noted", "neutral", 0),
    ],
)
def test_reply_classification(text: str, category: str, delta: int) -> None:
    assert classify_whatsapp_reply(text) == (category, delta)


# --------------------------------------------------------------------------- #
# Gateway transport
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_send_uses_the_documented_wa_akg_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json({"id": "wamid.42", "status": "sent"})

    client = _client(handler)
    try:
        service = WhatsAppService(settings=_settings(), client=client)
        result = await service.send_whatsapp_message("+967770447622", "hello there")
    finally:
        await client.aclose()

    assert result["success"] is True
    assert result["message_id"] == "wamid.42"
    request = seen[0]
    assert request.url.path == f"/api/messages/{SESSION}/967770447622@s.whatsapp.net/send"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.content) == {"message": "hello there"}


@pytest.mark.asyncio
async def test_disconnected_session_is_reported() -> None:
    client = _client(lambda request: _json({"message": "Session not connected"}, 401))
    try:
        service = WhatsAppService(settings=_settings(), client=client)
        result = await service.send_whatsapp_message("+967770447622", "hello")
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["error_code"] == "session_disconnected"
    assert result["status_code"] == 401


@pytest.mark.asyncio
async def test_rate_limit_is_retryable() -> None:
    client = _client(
        lambda request: httpx.Response(
            429, json={"message": "slow down"}, headers={"retry-after": "12"}
        )
    )
    try:
        service = WhatsAppService(settings=_settings(), client=client)
        result = await service.send_whatsapp_message("+967770447622", "hello")
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["error_code"] == "rate_limited"
    assert result["retryable"] is True


@pytest.mark.asyncio
async def test_invalid_number_never_reaches_the_network() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        seen.append(request)
        return _json({"id": "never"})

    client = _client(handler)
    try:
        service = WhatsAppService(settings=_settings(), client=client)
        result = await service.send_whatsapp_message("12345", "hello")
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["error_code"] == "invalid_recipient"
    assert seen == []


@pytest.mark.asyncio
async def test_unconfigured_gateway_is_reported_without_a_request() -> None:
    client = _client(lambda request: _json({"id": "never"}))
    try:
        service = WhatsAppService(
            settings=_settings(wa_akg_api_key=""), client=client
        )
        result = await service.send_whatsapp_message("+967770447622", "hello")
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["error_code"] == "whatsapp_error"
    assert "WA_AKG_API_KEY" in (result["error"] or "")


# --------------------------------------------------------------------------- #
# Broadcast pacing
# --------------------------------------------------------------------------- #
class _Recipient:
    def __init__(self, phone: str) -> None:
        self.id = uuid.uuid4()
        self.phone = phone
        self.full_name = "Recipient"


@pytest.mark.asyncio
async def test_broadcast_paces_messages_and_tracks_each_recipient() -> None:
    """A broadcast waits 10-30s between messages and never reuses a UUID."""
    sent: list[str] = []
    sleeps: list[float] = []
    links: list[uuid.UUID] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["message"]
        sent.append(body)
        for token in body.split():
            if "/api/v1/track/whatsapp/" in token:
                links.append(uuid.UUID(token.rsplit("/", 1)[-1]))
        return _json({"data": {"id": f"wamid.{len(sent)}"}})

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = _client(handler)
    try:
        service = WhatsAppService(settings=_settings(), client=client)
        result = await service.send_whatsapp_broadcast(
            [_Recipient("+967770447622"), _Recipient("+967770447623"), _Recipient("+967770447624")],
            "IT: re-authenticate: {{link}}",
            uuid.uuid4(),
            sleep=fake_sleep,
        )
    finally:
        await client.aclose()

    assert result["sent"] == 3
    assert result["failed"] == 0
    assert len(sleeps) == 2
    assert all(10 <= value <= 30 for value in sleeps)
    assert len(set(links)) == 3
    assert all(str(link) in body for link, body in zip(links, sent))


# --------------------------------------------------------------------------- #
# Launcher wiring
# --------------------------------------------------------------------------- #
class _FakeWhatsApp:
    """Capture what the launcher asks WA-AKG to send."""

    def __init__(self, result: dict | None = None) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.result = result or {
            "success": True,
            "message_id": "wamid.launch",
            "error": None,
        }

    def configuration_status(self) -> dict:
        return {"valid": True, "missing": []}

    def delay_between_messages(self) -> float:
        return 10.0

    async def send_whatsapp_message(self, to_phone, message, tracking_uuid=None) -> dict:
        self.sent.append((to_phone, message, str(tracking_uuid) if tracking_uuid else None))
        return self.result


def _launcher(whatsapp: _FakeWhatsApp) -> CampaignLauncher:
    settings = _settings()
    return CampaignLauncher(
        personalizer=TemplatePersonalizer(settings),
        whatsapp_service=whatsapp,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_launcher_sends_whatsapp_with_the_short_tracker(db: AsyncSession) -> None:
    whatsapp = _FakeWhatsApp()
    launcher = _launcher(whatsapp)
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="whatsapp",
        provider="wa-akg",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    message_id = await launcher._send_whatsapp(
        "+967770447622",
        f"HR: sign here http://testserver/api/v1/track/whatsapp/{tracking.tracking_uuid}",
        tracking,
        db,
        department="IT",
        manual_landing_page=None,
    )

    assert message_id == "wamid.launch"
    phone, body, sent_uuid = whatsapp.sent[0]
    assert phone == "+967770447622"
    assert sent_uuid == str(tracking.tracking_uuid)
    assert f"http://testserver/s/{tracking.short_code}" in body
    assert "/api/v1/track/" not in body


@pytest.mark.asyncio
async def test_launcher_refuses_an_unconfigured_gateway(db: AsyncSession) -> None:
    whatsapp = _FakeWhatsApp()
    whatsapp.configuration_status = lambda: {"valid": False, "missing": ["WA_AKG_SESSION_ID"]}  # type: ignore[assignment]
    launcher = _launcher(whatsapp)
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="whatsapp",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    with pytest.raises(RuntimeError, match="WA_AKG_SESSION_ID"):
        await launcher._send_whatsapp("+967770447622", "hello", tracking, db)
    assert whatsapp.sent == []


@pytest.mark.asyncio
async def test_launcher_pauses_between_two_whatsapp_messages(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anti-ban pause is honoured between consecutive sends."""
    whatsapp = _FakeWhatsApp()
    launcher = _launcher(whatsapp)
    import app.services.campaign_launcher as launcher_module

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(launcher_module.asyncio, "sleep", fake_sleep)
    first = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="whatsapp",
        tracking_uuid=uuid.uuid4(),
    )
    second = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="whatsapp",
        tracking_uuid=uuid.uuid4(),
    )
    db.add_all([first, second])
    await db.flush()

    await launcher._send_whatsapp("+967770447622", "one", first, db)
    await launcher._send_whatsapp("+967770447623", "two", second, db)

    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 10


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
async def _whatsapp_tracking(
    db: AsyncSession, organization: Organization, *, department: str = "IT"
) -> tuple[EmailTracking, HumanAsset]:
    suffix = uuid.uuid4().hex[:8]
    employee = HumanAsset(
        organization_id=organization.id,
        first_name="WhatsApp",
        last_name="Target",
        email=f"wa-{suffix}@example.com",
        department=department,
        phone="+967770447622",
        job_title="Engineer",
        access_level=3,
        is_active=True,
        behavioral_category="hesitant",
    )
    template = EmailTemplate(
        organization_id=organization.id,
        name=f"wa template {suffix}",
        subject="VPN certificate",
        body_html="Your VPN expired",
        channel="whatsapp",
        target_department=department,
    )
    db.add_all([employee, template])
    await db.flush()
    campaign = EmailCampaign(
        organization_id=organization.id,
        name=f"wa campaign {suffix}",
        channel="whatsapp",
        template_id=template.id,
        channel_config={"whatsapp": {"target_department": "it"}},
        target_employee_ids=[str(employee.id)],
    )
    db.add(campaign)
    await db.flush()
    row = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template.id,
        channel="whatsapp",
        provider="wa-akg",
        tracking_uuid=uuid.uuid4(),
        provider_message_id="wamid.seed",
        sent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row, employee


@pytest.mark.asyncio
async def test_webhook_read_receipt_marks_the_row_and_logs_once(
    client, db: AsyncSession, organization: Organization
) -> None:
    row, _ = await _whatsapp_tracking(db, organization)
    await db.commit()

    payload = {"event": "message.read", "data": {"messageId": "wamid.seed", "sessionId": SESSION}}
    first = await client.post("/api/v1/webhooks/whatsapp", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["handled"] is True

    refreshed = await db.get(EmailTracking, row.id)
    await db.refresh(refreshed)
    assert refreshed.read_at is not None
    assert refreshed.delivery_status == "read"

    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type == EVENT_WHATSAPP_READ,
            )
        )
    ).scalars().all()
    assert len(events) == 1

    second = await client.post("/api/v1/webhooks/whatsapp", json=payload)
    assert second.status_code == 200
    assert second.json()["detail"]["duplicate"] is True


@pytest.mark.asyncio
async def test_webhook_reply_with_secret_penalises_elo(
    client, db: AsyncSession, organization: Organization
) -> None:
    row, employee = await _whatsapp_tracking(db, organization)
    before = employee.elo_score
    await db.commit()

    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        json={
            "event": "message.received",
            "data": {
                "key": {"remoteJid": "967770447622@s.whatsapp.net", "id": "wamid.reply1"},
                "message": {"conversation": "ok, the code is 4821"},
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["handled"] is True
    assert response.json()["detail"]["category"] == "disclosed"

    refreshed = await db.get(HumanAsset, employee.id)
    await db.refresh(refreshed)
    assert refreshed.elo_score == before - 15

    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type == EVENT_WHATSAPP_REPLIED,
            )
        )
    ).scalars().all()
    assert len(events) == 1
    # The reply text itself is never persisted.
    assert "4821" not in json.dumps(events[0].details)


@pytest.mark.asyncio
async def test_webhook_suspicious_reply_rewards_elo(
    client, db: AsyncSession, organization: Organization
) -> None:
    _, employee = await _whatsapp_tracking(db, organization)
    before = employee.elo_score
    await db.commit()

    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        json={
            "event": "message.received",
            "data": {
                "key": {"remoteJid": "967770447622@s.whatsapp.net"},
                "message": {"conversation": "This is phishing, I am reporting it"},
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["detail"]["category"] == "suspicious"

    refreshed = await db.get(HumanAsset, employee.id)
    await db.refresh(refreshed)
    assert refreshed.elo_score == before + 10


@pytest.mark.asyncio
async def test_webhook_connection_update_records_session_state(
    client, admin_user, auth_headers
) -> None:
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        json={"event": "connection.update", "data": {"state": "connected", "sessionId": SESSION}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["detail"]["status"] == "connected"

    # Diagnostics are operator-only: anonymous callers must not read the
    # gateway session state or the list of missing settings.
    anonymous = await client.get("/api/v1/webhooks/whatsapp/status")
    assert anonymous.status_code == 401

    status = await client.get("/api/v1/webhooks/whatsapp/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["session"]["status"] == "connected"


@pytest.mark.asyncio
async def test_webhook_unknown_recipient_is_acknowledged(client) -> None:
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        json={"event": "message.read", "data": {"messageId": "wamid.unknown"}},
    )
    assert response.status_code == 200
    assert response.json()["handled"] is False


@pytest.mark.asyncio
async def test_webhook_rejects_a_wrong_token(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "wa_akg_webhook_secret", "s3cret", raising=False)
    try:
        response = await client.post(
            "/api/v1/webhooks/whatsapp",
            json={"event": "connection.update", "data": {"state": "connected"}},
            headers={"X-Webhook-Token": "nope"},
        )
        assert response.status_code == 401
        ok = await client.post(
            "/api/v1/webhooks/whatsapp",
            json={"event": "connection.update", "data": {"state": "connected"}},
            headers={"X-Webhook-Token": "s3cret"},
        )
        assert ok.status_code == 200
    finally:
        monkeypatch.undo()


# --------------------------------------------------------------------------- #
# Tracking endpoint
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_track_endpoint_redirects_to_the_resolved_lure_page(
    client, db: AsyncSession, organization: Organization
) -> None:
    row, _ = await _whatsapp_tracking(db, organization, department="IT")
    await db.commit()

    response = await client.get(
        f"/api/v1/track/whatsapp/{row.tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert f"/whatsapp-lure/{row.tracking_uuid}" in location
    assert location.endswith("?page=cisco_vpn")

    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type == EVENT_WHATSAPP_CLICKED,
            )
        )
    ).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_track_endpoint_honours_an_explicit_page(
    client, db: AsyncSession, organization: Organization
) -> None:
    row, _ = await _whatsapp_tracking(db, organization, department="IT")
    await db.commit()

    response = await client.get(
        f"/api/v1/track/whatsapp/{row.tracking_uuid}?page=hr_portal",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("?page=hr_portal")
