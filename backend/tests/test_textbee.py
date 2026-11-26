"""TextBee SMS gateway integration.

The HTTP layer uses ``httpx.MockTransport``: no test sends a real SMS, spends
account credit, or needs a real API key.  The tests assert the documented
TextBee request shape (``x-api-key``, ``recipients``/``message``/``deviceId``)
and that provider failures are returned as data instead of raised.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    Organization,
    TrainingInteraction,
)
from app.services.campaign_launcher import CampaignLauncher
from app.services.template_personalizer import TemplatePersonalizer
from app.services.textbee_service import (
    TextBeeService,
    is_e164_phone,
)
from app.services.tracking_service import (
    EVENT_SMS_CLICKED,
    EVENT_SMS_SUBMITTED,
)


def _settings(**overrides: object) -> Settings:
    """Return deterministic settings with a complete fake TextBee setup."""
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "base_url": "http://testserver",
        "textbee_api_key": "txb_test_key",
        "textbee_device_id": "dev_test_1",
        "textbee_base_url": "https://api.textbee.test/api/v1",
        "sms_provider": "textbee",
        # Deterministic, offline short links: no external shortener in tests.
        "short_link_provider": "none",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_send_sms_uses_the_documented_contract() -> None:
    """One POST to /gateway/send-sms with the key, recipients and device."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json({"data": {"smsBatchId": "batch_123", "deviceId": "dev_test_1"}})

    client = _client(handler)
    try:
        result = await TextBeeService(settings=_settings(), client=client).send_sms(
            "+967770447622", "رمز التحقق الخاص بك هو 4471"
        )
    finally:
        await client.aclose()

    assert result["success"] is True
    assert result["batch_id"] == "batch_123"
    assert result["provider"] == "textbee"

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://api.textbee.test/api/v1/gateway/send-sms"
    )
    assert request.headers["x-api-key"] == "txb_test_key"
    assert request.headers["content-type"] == "application/json"
    body = __import__("json").loads(request.content)
    assert body == {
        "recipients": ["+967770447622"],
        "message": "رمز التحقق الخاص بك هو 4471",
        "deviceId": "dev_test_1",
    }


@pytest.mark.asyncio
async def test_send_sms_rejects_a_non_e164_recipient_without_http() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _json({"data": {"smsBatchId": "unused"}})

    client = _client(handler)
    try:
        result = await TextBeeService(settings=_settings(), client=client).send_sms(
            "0770447622", "hello"
        )
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["error_code"] == "invalid_recipient"
    assert calls == []
    assert is_e164_phone("+967770447622") is True
    assert is_e164_phone("0770447622") is False


@pytest.mark.asyncio
async def test_missing_configuration_is_reported_not_raised() -> None:
    result = await TextBeeService(
        settings=_settings(textbee_api_key="")
    ).send_sms("+967770447622", "hello")

    assert result["success"] is False
    assert result["error_code"] == "textbee_error"
    assert "TEXTBEE_API_KEY" in (result["error"] or "")


@pytest.mark.asyncio
async def test_provider_401_is_returned_as_failure_data() -> None:
    client = _client(lambda _: _json({"message": "Invalid API key"}, 401))
    try:
        result = await TextBeeService(settings=_settings(), client=client).send_sms(
            "+967770447622", "hello"
        )
    finally:
        await client.aclose()

    assert result["success"] is False
    assert result["status_code"] == 401
    assert "Invalid API key" in (result["error"] or "")


@pytest.mark.asyncio
async def test_device_id_is_resolved_from_the_account_when_unset() -> None:
    """A blank TEXTBEE_DEVICE_ID uses the account's default phone."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json(
                {
                    "data": [
                        {"_id": "other", "enabled": True, "isDefault": False},
                        {"_id": "default_dev", "enabled": True, "isDefault": True},
                    ]
                }
            )
        bodies.append(__import__("json").loads(request.content))
        return _json({"data": {"smsBatchId": "batch_default"}})

    client = _client(handler)
    try:
        service = TextBeeService(
            settings=_settings(textbee_device_id=""), client=client
        )
        result = await service.send_sms("+967770447622", "hello")
    finally:
        await client.aclose()

    assert result["success"] is True
    assert bodies[0]["deviceId"] == "default_dev"


# --------------------------------------------------------------------------- #
# Launcher wiring
# --------------------------------------------------------------------------- #
class _FakeTextBee:
    """Capture what the launcher asks TextBee to send."""

    def __init__(self, result: dict | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self._result = result or {
            "success": True,
            "batch_id": "batch_launch",
            "error": None,
        }

    async def send_sms(self, to_phone: str, message: str) -> dict:
        self.sent.append((to_phone, message))
        return self._result


def _launcher(textbee: _FakeTextBee, settings: Settings):
    personalizer = TemplatePersonalizer(settings)
    return CampaignLauncher(
        personalizer=personalizer,
        textbee_service=textbee,
    )


@pytest.mark.asyncio
async def test_launcher_sends_sms_through_textbee_with_the_sms_tracker(
    db: AsyncSession,
) -> None:
    """The SMS body carries a short link and the batch id is stored."""
    textbee = _FakeTextBee()
    launcher = _launcher(textbee, _settings())
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    message_id = await launcher._send_sms(
        "+967770447622",
        f"تنبيه: حدّث كلمة المرور http://testserver/api/v1/track/click/{tracking.tracking_uuid}",
        tracking,
        db,
    )

    assert message_id == "batch_launch"
    assert len(textbee.sent) == 1
    phone, body = textbee.sent[0]
    assert phone == "+967770447622"
    assert f"http://testserver/s/{tracking.short_code}" in body
    assert "/api/v1/track/" not in body


@pytest.mark.asyncio
async def test_launcher_refuses_to_send_when_textbee_is_unconfigured(
    db: AsyncSession,
) -> None:
    """There is no second provider: an unconfigured TextBee is a clear error."""
    textbee = _FakeTextBee()
    launcher = _launcher(textbee, _settings(textbee_api_key=""))
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    with pytest.raises(RuntimeError, match="TextBee is not configured"):
        await launcher._send_sms("+967770447622", "hello", tracking, db)

    assert textbee.sent == []


@pytest.mark.asyncio
async def test_launcher_raises_when_textbee_rejects_the_message(
    db: AsyncSession,
) -> None:
    textbee = _FakeTextBee(
        {"success": False, "batch_id": None, "error": "Plan limit reached"}
    )
    launcher = _launcher(textbee, _settings())
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    with pytest.raises(RuntimeError, match="Plan limit reached"):
        await launcher._send_sms("+967770447622", "hello", tracking, db)


@pytest.mark.asyncio
async def test_launch_records_textbee_as_provider_and_sms_sent_event(
    db: AsyncSession, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An SMS launch stores the real transport, batch id and ``sms_sent``."""
    from app.models import EmailTemplate

    suffix = uuid.uuid4().hex[:8]
    template = EmailTemplate(
        organization_id=organization.id,
        name=f"sms live {suffix}",
        subject="تنبيه",
        body_html="مرحباً {{first_name}}، حدّث كلمة المرور: {{tracking_url}}",
        channel="sms",
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
    )
    employee = HumanAsset(
        organization_id=organization.id,
        email=f"textbee-{suffix}@example.com",
        first_name="Hamed",
        last_name="Test",
        phone="+967770447622",
        access_level=1,
        is_active=True,
        elo_score=1000,
    )
    db.add_all([template, employee])
    await db.flush()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=f"textbee campaign {suffix}",
        channel="sms",
        status="draft",
        is_mandatory_training=True,
        target_employee_ids=[str(employee.id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    sent_bodies: list[str] = []

    async def fake_send_sms(self, to_phone: str, message: str) -> dict:  # noqa: ANN001
        sent_bodies.append(message)
        return {"success": True, "batch_id": "batch_launch_test", "error": None}

    monkeypatch.setattr(TextBeeService, "send_sms", fake_send_sms)
    launcher = CampaignLauncher(personalizer=TemplatePersonalizer(_settings()))
    result = await launcher.launch_campaign(campaign.id, db)

    assert result["sent"] == 1
    assert result["failed"] == 0
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.provider == "textbee"
    assert row.provider_message_id == "batch_launch_test"
    assert f"/s/{row.short_code}" in sent_bodies[0]
    assert "/api/v1/track/" not in sent_bodies[0]

    events = (
        await db.execute(
            select(TrainingInteraction.event_type).where(
                TrainingInteraction.tracking_id == row.id
            )
        )
    ).scalars().all()
    assert "sms_sent" in events


def test_sms_render_drops_the_email_design_and_disclosure() -> None:
    """An SMS body is the lure text only: no branded shell, no disclaimer."""
    template = SimpleNamespace(
        channel="sms",
        subject="IT Security Alert",
        body_html=(
            "<p>Dear {{first_name}}, verify your {{company_name}} account "
            "immediately: {{link}}</p>"
        ),
        # Even a legacy design payload must be ignored for SMS.
        design_json={"blocks": []},
    )
    employee = SimpleNamespace(
        first_name="Hamed",
        last_name="Test",
        email="h@example.com",
        department="IT",
        job_title="Engineer",
        phone="+967770447622",
    )
    organization = SimpleNamespace(
        name="Acme Corporation",
        company_name="Acme Corporation",
        logo_url=None,
        brand_color=None,
        primary_color=None,
        secondary_color=None,
        domain="example.com",
    )
    uid = uuid.uuid4()
    text = TemplatePersonalizer(_settings()).personalize_text(
        template, employee, organization, uid
    )["text_content"]

    assert "{{link}}" not in text
    assert f"http://testserver/api/v1/track/click/{uid}" in text
    assert text.startswith("Dear Hamed")
    # Scan the copy only: the test base URL itself contains "testserver".
    copy = text.split("http", 1)[0].lower()
    for forbidden in ("simulation", "training", "test", "a message from"):
        assert forbidden not in copy
    assert text.count("http") == 1


@pytest.mark.asyncio
async def test_launcher_rewrites_link_to_a_short_url(db: AsyncSession) -> None:
    """``{{link}}`` ends up as a short link, never the long tracker."""
    textbee = _FakeTextBee()
    launcher = _launcher(textbee, _settings())
    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    await launcher._send_sms(
        "+967770447622",
        f"Verify now: http://testserver/api/v1/track/click/{tracking.tracking_uuid}",
        tracking,
        db,
    )

    body = textbee.sent[0][1]
    assert f"http://testserver/s/{tracking.short_code}" in body
    assert "/api/v1/track/" not in body
    assert body.count("http") == 1


# --------------------------------------------------------------------------- #
# Tracking endpoints
# --------------------------------------------------------------------------- #
async def _sms_tracking(
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    template_id: uuid.UUID,
) -> EmailTracking:
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template_id,
        name="Smishing test",
        channel="sms",
        status="active",
        total_targets=1,
    )
    db.add(campaign)
    await db.flush()
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template_id,
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    await db.refresh(employee)
    return tracking


@pytest.mark.asyncio
async def test_sms_click_redirects_and_is_score_neutral(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
) -> None:
    employee.phone = "+967770447622"
    employee.elo_score = 1000
    await db.commit()
    tracking = await _sms_tracking(db, organization, employee, custom_template.id)
    before = employee.elo_score

    response = await client.get(f"/api/v1/track/sms/{tracking.tracking_uuid}")

    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/sms-lure/{tracking.tracking_uuid}"
    )
    await db.refresh(employee)
    assert employee.elo_score == before

    event = await db.scalar(
        select(TrainingInteraction.event_type).where(
            TrainingInteraction.tracking_id == tracking.id,
            TrainingInteraction.event_type == EVENT_SMS_CLICKED,
        )
    )
    assert event == EVENT_SMS_CLICKED


@pytest.mark.asyncio
async def test_sms_submission_applies_minus_40_once(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
) -> None:
    employee.phone = "+967770447622"
    employee.elo_score = 1000
    await db.commit()
    tracking = await _sms_tracking(db, organization, employee, custom_template.id)
    before = employee.elo_score

    first = await client.post(
        "/api/v1/track/sms/submit", json={"tracking_uuid": str(tracking.tracking_uuid)}
    )
    assert first.status_code == 200, first.text
    assert first.json()["elo_delta"] == -40
    assert first.json()["already_recorded"] is False
    assert first.json()["redirect_url"].endswith(
        f"/training/{tracking.tracking_uuid}?channel=sms"
    )

    await db.refresh(employee)
    assert employee.elo_score == before - 40

    second = await client.post(
        "/api/v1/track/sms/submit", json={"tracking_uuid": str(tracking.tracking_uuid)}
    )
    assert second.status_code == 200
    assert second.json()["already_recorded"] is True
    assert second.json()["elo_delta"] == 0
    await db.refresh(employee)
    assert employee.elo_score == before - 40

    events = (
        await db.execute(
            select(TrainingInteraction.event_type).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == EVENT_SMS_SUBMITTED,
            )
        )
    ).scalars().all()
    assert events == [EVENT_SMS_SUBMITTED]


@pytest.mark.asyncio
async def test_short_link_redirects_and_counts_clicks(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
) -> None:
    """``/s/{code}`` records sms_clicked, counts the click and redirects."""
    from app.models import ShortLink
    from app.services.short_link_service import ShortLinkService

    employee.phone = "+967770447622"
    await db.commit()
    tracking = await _sms_tracking(db, organization, employee, custom_template.id)
    link = await ShortLinkService(_settings()).ensure_link(db, tracking)
    await db.commit()

    custom_template.target_department = "IT"
    await db.commit()
    context = await client.get(f"/api/v1/track/context/{tracking.tracking_uuid}")
    assert context.status_code == 200
    assert context.json()["template_category"] == "IT"

    response = await client.get(f"/s/{link.code}")

    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/sms-lure/{tracking.tracking_uuid}"
    )
    await db.refresh(link)
    assert link.clicks == 1
    assert link.last_clicked_at is not None
    event = await db.scalar(
        select(TrainingInteraction.event_type).where(
            TrainingInteraction.tracking_id == tracking.id,
            TrainingInteraction.event_type == EVENT_SMS_CLICKED,
        )
    )
    assert event == EVENT_SMS_CLICKED

    missing = await client.get("/s/nope404")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_short_link_is_reused_for_the_same_tracking(
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
) -> None:
    """Regenerating a link reuses the persisted code (stable SMS text)."""
    from app.services.short_link_service import ShortLinkService

    tracking = await _sms_tracking(db, organization, employee, custom_template.id)
    service = ShortLinkService(_settings())
    first = await service.ensure_link(db, tracking)
    second = await service.ensure_link(db, tracking)

    assert first.code == second.code
    assert len(first.code) == 6
    assert first.target_path == "/sms-lure/" + str(tracking.tracking_uuid)
    assert service.public_url(first.code) == f"http://testserver/s/{first.code}"


def test_sms_template_body_is_capped_at_170_characters() -> None:
    """The API schema rejects an SMS body longer than one short segment."""
    from pydantic import ValidationError

    from app.schemas.email_template import (
        SMS_BODY_MAX_LENGTH,
        EmailTemplateCreate,
        sms_body_length,
    )

    assert SMS_BODY_MAX_LENGTH == 170
    long_body = "A" * 171
    with pytest.raises(ValidationError, match="limit is 170"):
        EmailTemplateCreate(
            name="Too long", subject="x", channel="sms", body_html=long_body
        )

    exact = "A" * 162 + "{{link}}"
    assert sms_body_length(exact) == 170
    template = EmailTemplateCreate(
        name="Exactly",
        subject="x",
        channel="sms",
        body_html=exact,
        target_department="IT",
    )
    assert template.target_department == "IT"
    # An email body is not capped: only the SMS channel is constrained.
    EmailTemplateCreate(
        name="Email", subject="x", channel="email", body_html="B" * 5000
    )


@pytest.mark.asyncio
async def test_sms_submission_rejects_an_unknown_link(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/track/sms/submit", json={"tracking_uuid": str(uuid.uuid4())}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sms_submission_requires_a_tracking_uuid(client: AsyncClient) -> None:
    response = await client.post("/api/v1/track/sms/submit", json={})
    assert response.status_code == 400
