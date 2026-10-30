"""QuickConnect SMS & WhatsApp gateway unit and integration tests.

Tests cover:
- QuickConnectService configuration and phone number normalization
- SMS and WhatsApp dispatching with mock HTTP responses
- Error conditions (401 Unauthorized, 402 Insufficient Balance, HTTP errors)
- Balance checking
- CampaignLauncher integration with QuickConnect routing
- Test API endpoints for QuickConnect verification and balance
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.quickconnect_service import (
    QuickConnectConfigurationError,
    QuickConnectSendError,
    QuickConnectService,
    normalize_phone,
)
from app.services.template_service import TemplatePersonalizer


def _qc_settings(**overrides: object) -> Settings:
    """Return deterministic settings with QuickConnect enabled."""
    values: dict[str, object] = {
        "base_url": "https://shield.example",
        "encryption_key": "ab" * 32,
        "quickconnect_api_key": "qc_live_testkey123456789",
        "quickconnect_api_url": "https://aalcgjgocszngpcqzjih.supabase.co/functions/v1/public-api",
        "sms_provider": "quickconnect",
        "whatsapp_provider": "quickconnect",
    }
    values.update(overrides)
    return Settings(**values)


# ============================================================================
# Phone Normalization Tests
# ============================================================================

def test_normalize_phone_yemen_local_9_digits():
    assert normalize_phone("771234567") == "771234567"
    assert normalize_phone("731234567") == "731234567"
    assert normalize_phone("701234567") == "701234567"
    assert normalize_phone("711234567") == "711234567"


def test_normalize_phone_yemen_with_zero():
    assert normalize_phone("0771234567") == "0771234567"


def test_normalize_phone_international_e164():
    assert normalize_phone("+967771234567") == "+967771234567"
    assert normalize_phone("00967771234567") == "+967771234567"
    assert normalize_phone("+966501234567") == "+966501234567"


def test_normalize_phone_strips_formatting():
    assert normalize_phone("+967 77-123-4567") == "+967771234567"
    assert normalize_phone("  077 123 4567  ") == "0771234567"


# ============================================================================
# QuickConnectService Tests
# ============================================================================

def test_service_configuration_status():
    svc = QuickConnectService(_qc_settings())
    assert svc.is_configured is True
    status = svc.configuration_status()
    assert status["configured"] is True
    assert status["provider"] == "quickconnect"
    assert status["api_url"] == "https://aalcgjgocszngpcqzjih.supabase.co/functions/v1/public-api"

    unconfigured = QuickConnectService(_qc_settings(quickconnect_api_key=""))
    assert unconfigured.is_configured is False
    assert unconfigured.configuration_status()["configured"] is False


@pytest.mark.asyncio
async def test_send_message_unconfigured_raises():
    svc = QuickConnectService(_qc_settings(quickconnect_api_key=""))
    with pytest.raises(QuickConnectConfigurationError):
        await svc.send_message(to_phone="771234567", text="Test", channel="sms")


@pytest.mark.asyncio
async def test_send_message_empty_body_raises():
    svc = QuickConnectService(_qc_settings())
    with pytest.raises(QuickConnectSendError):
        await svc.send_message(to_phone="771234567", text="", channel="sms")


@pytest.mark.asyncio
async def test_send_sms_success():
    fake_response_data = {
        "ids": ["msg-uuid-12345"],
        "status": "queued",
        "balance_yer": 90,
    }

    mock_response = httpx.Response(
        status_code=201,
        json=fake_response_data,
        request=httpx.Request("POST", "https://example.com"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = QuickConnectService(_qc_settings(), http_client=mock_client)
    msg_id = await svc.send_sms(to_phone="0771234567", text="تنبيه أمني عاجل")
    assert msg_id == "msg-uuid-12345"

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["channel"] == "sms"
    assert call_kwargs["json"]["to"] == "0771234567"
    assert call_kwargs["json"]["body"] == "تنبيه أمني عاجل"


@pytest.mark.asyncio
async def test_send_whatsapp_success():
    fake_response_data = {
        "ids": ["wa-uuid-99999"],
        "status": "queued",
        "balance_yer": 80,
    }

    mock_response = httpx.Response(
        status_code=201,
        json=fake_response_data,
        request=httpx.Request("POST", "https://example.com"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = QuickConnectService(_qc_settings(), http_client=mock_client)
    msg_id = await svc.send_whatsapp(to_phone="+967731234567", text="رمز التحقق الخاص بك")
    assert msg_id == "wa-uuid-99999"


@pytest.mark.asyncio
async def test_send_message_401_error():
    mock_response = httpx.Response(
        status_code=401,
        json={"error": "Invalid API key"},
        request=httpx.Request("POST", "https://example.com"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = QuickConnectService(_qc_settings(), http_client=mock_client)
    with pytest.raises(QuickConnectConfigurationError) as exc_info:
        await svc.send_sms(to_phone="771234567", text="Test")
    assert "rejected API key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_message_402_insufficient_balance():
    mock_response = httpx.Response(
        status_code=402,
        json={"error": "Insufficient balance. Required: 10 YER"},
        request=httpx.Request("POST", "https://example.com"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = QuickConnectService(_qc_settings(), http_client=mock_client)
    with pytest.raises(QuickConnectSendError) as exc_info:
        await svc.send_sms(to_phone="771234567", text="Test")
    assert "insufficient balance" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_balance_success():
    mock_response = httpx.Response(
        status_code=200,
        json={"balance_yer": 100},
        request=httpx.Request("GET", "https://example.com"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_response

    svc = QuickConnectService(_qc_settings(), http_client=mock_client)
    balance = await svc.get_balance()
    assert balance["balance_yer"] == 100


# ============================================================================
# CampaignLauncher Integration with QuickConnect
# ============================================================================

class FakeQuickConnectService:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.sms: list[dict[str, str]] = []
        self.whatsapp: list[dict[str, str]] = []
        self.counter = 0

    @property
    def is_configured(self) -> bool:
        return self.valid

    def configuration_status(self, channel: str = "sms") -> dict:
        return {
            "valid": self.valid,
            "configured": self.valid,
            "provider": "quickconnect",
            "channel": channel,
            "missing": [] if self.valid else ["QUICKCONNECT_API_KEY"],
        }

    async def send_sms(self, to_phone: str, text: str) -> str:
        if not self.valid:
            raise QuickConnectConfigurationError("Not configured")
        self.counter += 1
        msg_id = f"qc-sms-{self.counter}"
        self.sms.append({"to": to_phone, "text": text, "id": msg_id})
        return msg_id

    async def send_whatsapp(self, to_phone: str, text: str) -> str:
        if not self.valid:
            raise QuickConnectConfigurationError("Not configured")
        self.counter += 1
        msg_id = f"qc-wa-{self.counter}"
        self.whatsapp.append({"to": to_phone, "text": text, "id": msg_id})
        return msg_id


async def _make_qc_fixture(
    db: AsyncSession,
    organization,
    *,
    channel: str = "sms",
    phone: str = "771234567",
) -> tuple[EmailCampaign, EmailTemplate, HumanAsset]:
    suffix = uuid.uuid4().hex[:8]
    template = EmailTemplate(
        organization_id=organization.id,
        name=f"QC {channel} template {suffix}",
        subject="تنبيه أمني",
        body_html="عزيزي {{first_name}}، اضغط على الرابط التالي: {{tracking_url}}",
        channel=channel,
        difficulty_level=3,
        is_built_in=False,
        is_active=True,
    )
    employee = HumanAsset(
        organization_id=organization.id,
        email=f"qc-{suffix}@example.com",
        first_name="Badr",
        last_name="Yemen",
        phone=phone,
        access_level=1,
        is_active=True,
    )
    db.add_all([template, employee])
    await db.flush()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name=f"QC {channel} campaign {suffix}",
        channel=channel,
        status="draft",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign, template, employee


@pytest.mark.asyncio
async def test_campaign_launcher_routes_sms_to_quickconnect(db: AsyncSession, organization):
    campaign, template, employee = await _make_qc_fixture(db, organization, channel="sms", phone="0771234567")
    qc_service = FakeQuickConnectService(valid=True)
    cfg = _qc_settings()
    personalizer = TemplatePersonalizer(cfg)

    launcher = CampaignLauncher(
        personalizer=personalizer,
        quickconnect_service=qc_service,
    )

    result = await launcher.launch_campaign(campaign.id, db)
    assert result["sent"] == 1
    assert result["failed"] == 0

    assert len(qc_service.sms) == 1
    assert qc_service.sms[0]["to"] == "0771234567"
    assert qc_service.whatsapp == []

    # Verify tracking record in database
    row = await db.scalar(select(EmailTracking).where(EmailTracking.campaign_id == campaign.id))
    assert row is not None
    assert row.channel == "sms"
    assert row.provider == "quickconnect"
    assert row.provider_message_id == "qc-sms-1"
    assert row.delivery_status == "submitted"


@pytest.mark.asyncio
async def test_campaign_launcher_routes_whatsapp_to_quickconnect(db: AsyncSession, organization):
    campaign, template, employee = await _make_qc_fixture(db, organization, channel="whatsapp", phone="+967733456789")
    qc_service = FakeQuickConnectService(valid=True)
    cfg = _qc_settings()
    personalizer = TemplatePersonalizer(cfg)

    launcher = CampaignLauncher(
        personalizer=personalizer,
        quickconnect_service=qc_service,
    )

    result = await launcher.launch_campaign(campaign.id, db)
    assert result["sent"] == 1
    assert result["failed"] == 0

    assert len(qc_service.whatsapp) == 1
    assert qc_service.whatsapp[0]["to"] == "+967733456789"
    assert qc_service.sms == []

    row = await db.scalar(select(EmailTracking).where(EmailTracking.campaign_id == campaign.id))
    assert row is not None
    assert row.channel == "whatsapp"
    assert row.provider == "quickconnect"
    assert row.provider_message_id == "qc-wa-1"
    assert row.delivery_status == "submitted"

