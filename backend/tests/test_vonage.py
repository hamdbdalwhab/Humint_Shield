"""Vonage SMS/WhatsApp delivery, receipts, previews and channel routing.

Every provider call in this module uses an in-memory double.  A real Vonage
credential is never required, and no test records a delivery that did not come
from a legitimate webhook payload.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.template_service import TemplatePersonalizer, html_to_text
from app.services.vonage_service import (
    VonageConfigurationError,
    VonageSendError,
    VonageService,
    is_e164_phone,
)
from app.services.vonage_webhook_service import VonageWebhookService


def _settings(**overrides: object) -> Settings:
    """Return deterministic settings with a complete fake Vonage setup."""
    values: dict[str, object] = {
        "base_url": "https://shield.example",
        "encryption_key": "ab" * 32,
        "vonage_api_key": "test-key",
        "vonage_api_secret": "test-secret",
        "vonage_sms_from": "Shield",
        "vonage_whatsapp_from": "14155238886",
    }
    values.update(overrides)
    return Settings(**values)


class FakeSmsClient:
    """Stand-in for ``vonage.Sms``."""

    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.payload: dict | None = None

    def send_message(self, payload: dict) -> object:
        self.payload = payload
        if self.error is not None:
            raise self.error
        return self.response


class FakeMessagesClient:
    """Stand-in for ``vonage.Messages``; both SDK method names are covered."""

    def __init__(
        self,
        response: object = None,
        *,
        method: str = "send_message",
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.payload: dict | None = None
        if method == "send":
            self.send = self._send  # type: ignore[attr-defined]
        else:
            self.send_message = self._send  # type: ignore[attr-defined]

    def _send(self, payload: dict) -> object:
        self.payload = payload
        if self.error is not None:
            raise self.error
        return self.response


def test_e164_validation() -> None:
    """Only international E.164 values are accepted."""
    assert is_e164_phone("+966500000000")
    assert is_e164_phone("+14155238886")
    assert not is_e164_phone("0500000000")
    assert not is_e164_phone("+0123456789")
    assert not is_e164_phone("+123")
    assert not is_e164_phone(None)


async def test_send_sms_builds_unicode_payload() -> None:
    """SMS uses the Unicode flag and strips the leading plus for Vonage."""
    client = FakeSmsClient(
        {"messages": [{"status": "0", "message-id": "sms-message-1"}]}
    )
    service = VonageService(_settings(), sms_client=client)

    message_id = await service.send_sms("+966500000000", "مرحباً بكم")

    assert message_id == "sms-message-1"
    assert client.payload == {
        "from": "Shield",
        "to": "966500000000",
        "text": "مرحباً بكم",
        "type": "unicode",
        "status-report-req": 1,
        "callback": "https://shield.example/api/v1/webhooks/vonage/dlr",
    }


async def test_send_sms_includes_webhook_token_in_callback() -> None:
    """The DLR callback carries the shared token when one is configured."""
    client = FakeSmsClient({"messages": [{"status": "0", "message-id": "sms-token"}]})
    service = VonageService(
        _settings(vonage_webhook_token="a b&c"), sms_client=client
    )

    await service.send_sms("+966500000000", "hello")

    assert client.payload is not None
    assert client.payload["callback"].endswith(
        "/api/v1/webhooks/vonage/dlr?token=a%20b%26c"
    )


async def test_send_sms_rejects_provider_error() -> None:
    """A non-zero Vonage status becomes a truthful send error."""
    client = FakeSmsClient(
        {"messages": [{"status": "4", "error-text": "Invalid credentials"}]}
    )
    service = VonageService(_settings(), sms_client=client)

    with pytest.raises(VonageSendError, match="Invalid credentials"):
        await service.send_sms("+966500000000", "hello")


async def test_send_sms_requires_configuration() -> None:
    """No SDK call is attempted when the channel is not configured."""
    client = FakeSmsClient({"messages": []})
    service = VonageService(
        _settings(vonage_api_key="", vonage_api_secret=""), sms_client=client
    )

    with pytest.raises(VonageConfigurationError, match="VONAGE_API_KEY"):
        await service.send_sms("+966500000000", "hello")
    assert client.payload is None


async def test_send_sms_rejects_invalid_recipient() -> None:
    """A malformed local phone is rejected before the provider sees it."""
    service = VonageService(_settings(), sms_client=FakeSmsClient({"messages": []}))
    with pytest.raises(VonageSendError, match="E.164"):
        await service.send_sms("0500000000", "hello")


async def test_send_whatsapp_builds_messages_payload() -> None:
    """WhatsApp uses the Messages API with sender and recipient sans plus."""
    client = FakeMessagesClient({"message_uuid": "wa-message-1"})
    service = VonageService(_settings(), messages_client=client)

    message_id = await service.send_whatsapp("+966500000000", "مرحباً")

    assert message_id == "wa-message-1"
    assert client.payload == {
        "channel": "whatsapp",
        "message_type": "text",
        "to": "966500000000",
        "from": "14155238886",
        "text": "مرحباً",
    }


async def test_send_whatsapp_supports_newer_send_method() -> None:
    """The service still works if a future SDK exposes ``send``."""
    client = FakeMessagesClient({"message_uuid": "wa-message-2"}, method="send")
    service = VonageService(_settings(), messages_client=client)

    assert await service.send_whatsapp("+966500000000", "hello") == "wa-message-2"


async def test_send_whatsapp_rejects_malformed_response() -> None:
    """A 200 response without a message UUID is a real failure."""
    client = FakeMessagesClient({"detail": "No message"})
    service = VonageService(_settings(), messages_client=client)

    with pytest.raises(VonageSendError, match="message_uuid"):
        await service.send_whatsapp("+966500000000", "hello")


async def test_send_whatsapp_requires_sender() -> None:
    """WhatsApp cannot be marked ready without a business/sandbox number."""
    service = VonageService(
        _settings(vonage_whatsapp_from=""), messages_client=FakeMessagesClient({})
    )
    with pytest.raises(VonageConfigurationError, match="VONAGE_WHATSAPP_FROM"):
        await service.send_whatsapp("+966500000000", "hello")


def test_vonage_partial_application_credentials_are_rejected() -> None:
    """An incomplete application credential pair must not send silently."""
    service = VonageService(_settings(vonage_application_id="app-id"))
    status = service.configuration_status("whatsapp")
    assert status["valid"] is False
    assert "VONAGE_APPLICATION_ID" in status["missing"]
    assert "VONAGE_PRIVATE_KEY" in status["missing"]
    with pytest.raises(VonageConfigurationError, match="VONAGE_APPLICATION_ID"):
        service._build_messages_client()


def test_vonage_messages_client_uses_jwt_and_custom_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Application credentials produce JWT auth and the optional sandbox host."""
    import vonage as vonage_sdk

    key_file = tmp_path / "private.key"
    key_file.write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    host: dict[str, str] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def api_host(self, value: str | None = None) -> str | None:
            if value is not None:
                host["value"] = value
            return host.get("value")

    class FakeMessages:
        def __init__(self, client: object) -> None:
            self.client = client

    monkeypatch.setattr(vonage_sdk, "Client", FakeClient)
    monkeypatch.setattr(vonage_sdk, "Messages", FakeMessages)
    settings = _settings(
        vonage_application_id="app-id",
        vonage_private_key=str(key_file),
        vonage_messages_base_url="https://messages-sandbox.nexmo.com/",
    )

    client = VonageService(settings)._build_messages_client()

    assert captured["application_id"] == "app-id"
    assert str(captured["private_key"]).startswith("-----BEGIN PRIVATE KEY-----")
    assert host["value"] == "https://messages-sandbox.nexmo.com"
    assert isinstance(client, FakeMessages)


def test_html_to_text_preserves_readable_copy() -> None:
    """HTML is reduced to readable text without scripts or markup."""
    result = html_to_text(
        "<style>.x{}</style><p>Hello &amp; welcome</p>"
        '<p><a href="https://example.com">Open</a></p><script>alert(1)</script>'
    )
    assert "Hello & welcome" in result
    assert "Open" in result
    assert "<" not in result
    assert "alert(1)" not in result


def test_personalize_text_appends_click_tracking_url() -> None:
    """The SMS/WhatsApp body always contains exactly one tracked click URL."""
    settings = _settings()
    personalizer = TemplatePersonalizer(settings)
    uid = uuid.uuid4()
    template = SimpleNamespace(
        subject="تنبيه أمني",
        body_html="<p>مرحباً {{first_name}}</p><p>افتح المستند من هنا.</p>",
    )
    employee = SimpleNamespace(
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
        department="Finance",
        job_title="Controller",
        manager_id=None,
    )
    organization = SimpleNamespace(name="Acme")

    result = personalizer.personalize_text(
        template, employee, organization, uid, settings.base_url
    )

    expected = f"https://shield.example/api/v1/track/click/{uid}"
    assert "مرحباً Jane" in result["text_content"]
    assert result["text_content"].count(expected) == 1
    assert result["tracking_url"] == expected


def test_personalize_text_does_not_duplicate_placeholder_url() -> None:
    """A template that already uses ``{{tracking_url}}`` is not doubled."""
    settings = _settings()
    personalizer = TemplatePersonalizer(settings)
    uid = uuid.uuid4()
    template = SimpleNamespace(
        subject="Alert",
        body_html="<p>Open: {{tracking_url}}</p>",
    )
    employee = SimpleNamespace(
        first_name="Jane",
        last_name="Doe",
        email="jane@example.com",
        department=None,
        job_title=None,
        manager_id=None,
    )
    result = personalizer.personalize_text(
        template, employee, SimpleNamespace(name="Acme"), uid, settings.base_url
    )
    expected = f"https://shield.example/api/v1/track/click/{uid}"
    assert result["text_content"].count(expected) == 1


async def _tracking_row(
    db: AsyncSession,
    organization,
    *,
    channel: str = "sms",
    provider_message_id: str = "sms-1",
    delivery_status: str = "submitted",
) -> EmailTracking:
    """Create a campaign recipient in the requested delivery state."""
    suffix = uuid.uuid4().hex[:8]
    employee = HumanAsset(
        organization_id=organization.id,
        email=f"recipient-{suffix}@example.com",
        first_name="Recipient",
        last_name="Test",
        phone="+966500000000",
        access_level=1,
        is_active=True,
    )
    template = EmailTemplate(
        organization_id=organization.id,
        name=f"Message {suffix}",
        subject="Alert",
        body_html="<p>Open {{tracking_url}}</p>",
        channel=channel,
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
    )
    db.add_all([employee, template])
    await db.flush()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=f"Campaign {suffix}",
        channel=channel,
        status="completed",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.flush()
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template.id,
        channel=channel,
        provider="vonage",
        tracking_uuid=uuid.uuid4(),
        sent_at=datetime.now(timezone.utc),
        provider_message_id=provider_message_id,
        delivery_status=delivery_status,
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


async def test_sms_dlr_sets_delivered_then_read(
    db: AsyncSession, organization
) -> None:
    """Real DLR statuses advance the receipt and are idempotent."""
    tracking = await _tracking_row(db, organization)
    service = VonageWebhookService()

    result = await service.record_sms_dlr(
        {
            "message-id": "sms-1",
            "status": "delivered",
            "message-timestamp": "2026-10-23 10:00:00",
            "err-code": "0",
        },
        db,
    )
    assert result["matched"] is True
    assert tracking.delivery_status == "delivered"
    assert tracking.delivered_at is not None
    delivered_at = tracking.delivered_at

    duplicate = await service.record_sms_dlr(
        {"message-id": "sms-1", "status": "delivered"}, db
    )
    assert duplicate["matched"] is True
    assert tracking.delivered_at == delivered_at

    read = await service.record_sms_dlr(
        {
            "message-id": "sms-1",
            "status": "read",
            "message-timestamp": "2026-10-23T10:05:00Z",
        },
        db,
    )
    assert read["status"] == "read"
    assert tracking.delivery_status == "read"
    assert tracking.read_at is not None

    # An at-least-once retry of the older status must not regress the row.
    await service.record_sms_dlr({"message-id": "sms-1", "status": "delivered"}, db)
    assert tracking.delivery_status == "read"


async def test_whatsapp_status_sets_read_and_error(
    db: AsyncSession, organization
) -> None:
    """WhatsApp receipts set read on success and preserve provider errors."""
    tracking = await _tracking_row(db, organization, channel="whatsapp", provider_message_id="wa-1")
    service = VonageWebhookService()

    result = await service.record_whatsapp_status(
        {
            "message_uuid": "wa-1",
            "status": "read",
            "timestamp": "2026-10-23T11:00:00Z",
        },
        db,
    )
    assert result["matched"] is True
    assert tracking.delivery_status == "read"
    assert tracking.read_at is not None

    # A stale failure callback cannot erase a read receipt.
    await service.record_whatsapp_status(
        {"message_uuid": "wa-1", "status": "rejected", "error": "spam"}, db
    )
    assert tracking.delivery_status == "read"
    assert tracking.delivery_error is None


async def test_failure_then_delivery_is_allowed(
    db: AsyncSession, organization
) -> None:
    """A preliminary failure may be corrected by a later delivered receipt."""
    tracking = await _tracking_row(
        db, organization, provider_message_id="sms-fail", delivery_status="submitted"
    )
    service = VonageWebhookService()

    await service.record_sms_dlr(
        {"message-id": "sms-fail", "status": "failed", "error-text": "temporary"},
        db,
    )
    assert tracking.delivery_status == "failed"
    assert tracking.delivery_error == "temporary"
    assert tracking.failed_at is not None

    await service.record_sms_dlr(
        {"message-id": "sms-fail", "status": "delivered"}, db
    )
    assert tracking.delivery_status == "delivered"
    assert tracking.delivery_error is None
    assert tracking.failed_at is None


async def test_webhook_is_scoped_to_channel(db: AsyncSession, organization) -> None:
    """An SMS receipt cannot mutate a WhatsApp row with the same provider id."""
    tracking = await _tracking_row(
        db, organization, channel="whatsapp", provider_message_id="shared-id"
    )
    service = VonageWebhookService()

    result = await service.record_sms_dlr(
        {"message-id": "shared-id", "status": "read"}, db
    )
    assert result["matched"] is False
    assert tracking.delivery_status == "submitted"


async def test_webhook_rejects_unknown_or_unsupported(
    db: AsyncSession, organization
) -> None:
    """Unknown ids and statuses are reported, never stored as delivered."""
    await _tracking_row(db, organization, provider_message_id="sms-known")
    service = VonageWebhookService()

    unknown = await service.record_sms_dlr(
        {"message-id": "missing", "status": "delivered"}, db
    )
    assert unknown["matched"] is False
    assert unknown["detail"] == "tracking row not found"

    unsupported = await service.record_sms_dlr(
        {"message-id": "sms-known", "status": "quantum"}, db
    )
    assert unsupported["matched"] is False
    assert "unsupported" in unsupported["detail"]


async def test_webhook_endpoint_requires_token_and_applies_receipt(
    client, db: AsyncSession, organization, monkeypatch
) -> None:
    """The public DLR endpoint is protected and commits a real receipt."""
    from app.api.v1.webhooks import vonage as webhook_api

    tracking = await _tracking_row(
        db, organization, provider_message_id="http-sms-1"
    )
    monkeypatch.setattr(
        webhook_api,
        "get_settings",
        lambda: SimpleNamespace(vonage_webhook_token="expected-token"),
    )

    rejected = await client.post(
        "/api/v1/webhooks/vonage/dlr",
        data={"message-id": "http-sms-1", "status": "delivered"},
    )
    assert rejected.status_code == 403

    accepted = await client.post(
        "/api/v1/webhooks/vonage/dlr",
        params={"token": "expected-token"},
        data={"message-id": "http-sms-1", "status": "delivered"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["matched"] is True
    await db.refresh(tracking)
    assert tracking.delivery_status == "delivered"


async def test_whatsapp_webhook_accepts_json_and_header_token(
    client, db: AsyncSession, organization, monkeypatch
) -> None:
    """The WhatsApp endpoint accepts JSON and the X-Vonage-Webhook-Token header."""
    from app.api.v1.webhooks import vonage as webhook_api

    tracking = await _tracking_row(
        db,
        organization,
        channel="whatsapp",
        provider_message_id="http-wa-1",
    )
    monkeypatch.setattr(
        webhook_api,
        "get_settings",
        lambda: SimpleNamespace(vonage_webhook_token="header-token"),
    )

    response = await client.post(
        "/api/v1/webhooks/vonage/whatsapp-status",
        headers={"X-Vonage-Webhook-Token": "header-token"},
        json={"message_uuid": "http-wa-1", "status": "read", "timestamp": "2026-10-23T12:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "read"
    await db.refresh(tracking)
    assert tracking.delivery_status == "read"


async def test_sms_dlr_get_callback(
    client, db: AsyncSession, organization, monkeypatch
) -> None:
    """Providers configured for GET can deliver a receipt in the query string."""
    from app.api.v1.webhooks import vonage as webhook_api

    tracking = await _tracking_row(
        db, organization, provider_message_id="get-sms-1"
    )
    monkeypatch.setattr(
        webhook_api,
        "get_settings",
        lambda: SimpleNamespace(vonage_webhook_token=""),
    )

    response = await client.get(
        "/api/v1/webhooks/vonage/dlr",
        params={"message-id": "get-sms-1", "status": "failed", "error-text": "no route"},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is True
    await db.refresh(tracking)
    assert tracking.delivery_status == "failed"
    assert tracking.delivery_error == "no route"


async def _phone_fixture(
    db: AsyncSession,
    organization,
    *,
    channel: str = "sms",
    phone: str | None = "+966500000000",
) -> tuple[EmailCampaign, EmailTemplate, HumanAsset]:
    """Create a draft phone campaign and one employee."""
    suffix = uuid.uuid4().hex[:8]
    template = EmailTemplate(
        organization_id=organization.id,
        name=f"{channel} template {suffix}",
        subject="تنبيه",
        body_html="مرحباً {{first_name}}، افتح الرابط: {{tracking_url}}",
        channel=channel,
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
    )
    employee = HumanAsset(
        organization_id=organization.id,
        email=f"phone-{suffix}@example.com",
        first_name="Sara",
        last_name="Test",
        phone=phone,
        access_level=1,
        is_active=True,
    )
    db.add_all([template, employee])
    await db.flush()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=f"{channel} campaign {suffix}",
        channel=channel,
        status="draft",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    await db.refresh(template)
    await db.refresh(employee)
    return campaign, template, employee


class FakeVonageService:
    """Recording SMS/WhatsApp transport with honest readiness reporting."""

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.sms: list[dict] = []
        self.whatsapp: list[dict] = []

    def configuration_status(self, channel: str) -> dict:
        return {
            "valid": self.valid,
            "missing": [] if self.valid else ["VONAGE_API_KEY", "VONAGE_API_SECRET"],
            "channel": channel,
            "from": "Shield",
        }

    async def send_sms(self, to_phone: str, text: str) -> str:
        self.sms.append({"to": to_phone, "text": text})
        return f"sms-{len(self.sms)}"

    async def send_whatsapp(self, to_phone: str, text: str) -> str:
        self.whatsapp.append({"to": to_phone, "text": text})
        return f"wa-{len(self.whatsapp)}"


@pytest.mark.parametrize("channel", ["sms", "whatsapp"])
async def test_launcher_routes_phone_channel_and_records_submitted(
    db: AsyncSession, organization, channel: str
) -> None:
    """SMS/WhatsApp dispatch stores provider ids and only a submitted state."""
    campaign, _, employee = await _phone_fixture(db, organization, channel=channel)
    transport = FakeVonageService()
    personalizer = TemplatePersonalizer(_settings())

    launcher = CampaignLauncher(
        personalizer=personalizer, vonage_service=transport
    )
    result = await launcher.launch_campaign(campaign.id, db)

    assert result["sent"] == 1
    assert result["failed"] == 0
    if channel == "sms":
        assert len(transport.sms) == 1
        assert transport.sms[0]["to"] == employee.phone
        assert transport.whatsapp == []
    else:
        assert len(transport.whatsapp) == 1
        assert transport.whatsapp[0]["to"] == employee.phone
        assert transport.sms == []

    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.channel == channel
    assert row.provider == "vonage"
    assert row.provider_message_id in {"sms-1", "wa-1"}
    assert row.sent_at is not None
    assert row.delivered_at is None
    assert row.read_at is None
    assert row.delivery_status == "submitted"
    assert "/api/v1/track/click/" in (
        transport.sms[0]["text"] if channel == "sms" else transport.whatsapp[0]["text"]
    )


async def test_launcher_blocks_phone_campaign_without_configuration(
    db: AsyncSession, organization
) -> None:
    """A direct/background launch cannot silently fail every recipient."""
    campaign, _, _ = await _phone_fixture(db, organization, channel="sms")
    launcher = CampaignLauncher(
        personalizer=TemplatePersonalizer(_settings()),
        vonage_service=FakeVonageService(valid=False),
    )

    with pytest.raises(CampaignLaunchError, match="not configured"):
        await launcher.launch_campaign(campaign.id, db)

    await db.refresh(campaign)
    assert campaign.status == "draft"
    rows = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert rows == []


async def test_launcher_records_phone_target_without_number(
    db: AsyncSession, organization
) -> None:
    """A missing number is recorded as a failure, not a sent message."""
    campaign, _, _ = await _phone_fixture(
        db, organization, channel="whatsapp", phone=None
    )
    launcher = CampaignLauncher(
        personalizer=TemplatePersonalizer(_settings()),
        vonage_service=FakeVonageService(),
    )

    result = await launcher.launch_campaign(campaign.id, db)

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert "no phone" in result["failures"][0]["error"]
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.delivery_status == "failed"
    assert "no phone" in (row.delivery_error or "")


async def test_employee_phone_api_validation(
    client, auth_headers, organization, employee
) -> None:
    """Employees can only be stored with E.164 numbers, and can be cleared."""
    base = f"/api/v1/organizations/{organization.id}/employees"
    invalid = await client.post(
        base,
        headers=auth_headers,
        json={
            "email": "invalid-phone@example.com",
            "first_name": "Invalid",
            "phone": "0500000000",
        },
    )
    assert invalid.status_code == 422

    created = await client.post(
        base,
        headers=auth_headers,
        json={
            "email": "valid-phone@example.com",
            "first_name": "Valid",
            "phone": "+966500000000",
        },
    )
    assert created.status_code == 201
    assert created.json()["phone"] == "+966500000000"

    updated = await client.put(
        f"{base}/{employee.id}",
        headers=auth_headers,
        json={"phone": "+14155238886"},
    )
    assert updated.status_code == 200
    assert updated.json()["phone"] == "+14155238886"

    cleared = await client.put(
        f"{base}/{employee.id}", headers=auth_headers, json={"phone": ""}
    )
    assert cleared.status_code == 200
    assert cleared.json()["phone"] is None


async def test_bulk_import_rejects_invalid_phone(
    client, auth_headers, organization
) -> None:
    """CSV import reports the bad row instead of storing an unusable number."""
    base = f"/api/v1/organizations/{organization.id}/employees"
    response = await client.post(
        f"{base}/bulk",
        headers=auth_headers,
        files={
            "file": (
                "employees.csv",
                "email,first_name,phone\nbulk@example.com,Bulk,0500000000\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 0
    assert body["skipped"] == 1
    assert any("E.164" in error for error in body["errors"])


async def _sms_template(db: AsyncSession, organization) -> EmailTemplate:
    template = EmailTemplate(
        organization_id=organization.id,
        name="SMS API Template",
        subject="Alert",
        body_html="Open {{tracking_url}}",
        channel="sms",
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def test_sms_campaign_requires_phone_for_every_target(
    client, auth_headers, db: AsyncSession, organization, employee, employees
) -> None:
    """SMS campaign creation rejects any target without a valid phone."""
    template = await _sms_template(db, organization)
    employee.phone = "+966500000000"
    await db.commit()
    base = f"/api/v1/organizations/{organization.id}/email-campaigns"

    accepted = await client.post(
        base,
        headers=auth_headers,
        json={
            "name": "SMS valid",
            "template_id": str(template.id),
            "channel": "sms",
            "target_employee_ids": [str(employee.id)],
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["channel"] == "sms"

    rejected = await client.post(
        base,
        headers=auth_headers,
        json={
            "name": "SMS invalid",
            "template_id": str(template.id),
            "channel": "sms",
            "target_employee_ids": [str(employees[0].id)],
        },
    )
    assert rejected.status_code == 400
    assert "missing phone" in rejected.json()["detail"]


async def test_sms_campaign_launch_blocked_without_credentials(
    client, auth_headers, db: AsyncSession, organization, employee, monkeypatch
) -> None:
    """Launch fails with 502 and leaves the draft untouched when unconfigured."""
    from app.api.v1 import campaigns as campaigns_api

    template = await _sms_template(db, organization)
    employee.phone = "+966500000000"
    await db.commit()
    created = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        headers=auth_headers,
        json={
            "name": "SMS unconfigured",
            "template_id": str(template.id),
            "channel": "sms",
            "target_employee_ids": [str(employee.id)],
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    unconfigured = _settings(
        vonage_api_key="",
        vonage_api_secret="",
        vonage_sms_from="",
        vonage_whatsapp_from="",
    )
    monkeypatch.setattr(campaigns_api, "get_settings", lambda: unconfigured)

    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/{campaign_id}/launch",
        headers=auth_headers,
    )
    assert response.status_code == 502
    assert "VONAGE_API_KEY" in response.json()["detail"]

    campaign = await db.get(EmailCampaign, uuid.UUID(campaign_id))
    await db.refresh(campaign)
    assert campaign.status == "draft"
    rows = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert rows == []


async def test_sms_template_preview_returns_plain_text(
    client, auth_headers, db: AsyncSession, organization, employee
) -> None:
    """The preview returns the actual text that would be handed to Vonage."""
    template = await _sms_template(db, organization)
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-templates/{template.id}/preview",
        headers=auth_headers,
        json={"employee_id": str(employee.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert "<" not in body["text_content"]
    assert "/api/v1/track/click/" in body["text_content"]
    assert body["subject"] == "Alert"


async def test_vonage_verify_reports_missing_and_configured(
    client, auth_headers, monkeypatch
) -> None:
    """Diagnostics expose readiness and webhook URLs without leaking secrets."""
    from app.api.v1 import test as diagnostics_api

    unconfigured = _settings(
        vonage_api_key="", vonage_api_secret="", vonage_whatsapp_from=""
    )
    monkeypatch.setattr(diagnostics_api, "get_settings", lambda: unconfigured)
    response = await client.get(
        "/api/v1/test/vonage/verify?channel=whatsapp", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "VONAGE_API_KEY" in body["missing"]
    assert "VONAGE_WHATSAPP_FROM" in body["missing"]
    assert body["webhook_urls"]["sms_dlr"].endswith("/api/v1/webhooks/vonage/dlr")

    configured = _settings(
        vonage_api_key="super-secret-key",
        vonage_api_secret="super-secret-secret",
    )
    monkeypatch.setattr(diagnostics_api, "get_settings", lambda: configured)
    response = await client.get(
        "/api/v1/test/vonage/verify?channel=sms", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["detail"]["from"] == "Shield"
    assert "super-secret-key" not in response.text
    assert "super-secret-secret" not in response.text
