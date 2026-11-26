"""API tests for the real IllyVoIP vishing channel.

The provider HTTP layer is covered in ``test_illyvoip.py``.  These tests replace
``IllyVoIPService``'s control methods so they can assert the API contract,
authorization, tracking persistence and error mapping without placing a call.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    Organization,
    TrainingInteraction,
    User,
)
from app.security import create_access_token, hash_password
from app.services.illyvoip_service import (
    IllyVoIPContentReviewError,
    IllyVoIPService,
    mask_phone,
)
from app.services.tracking_service import (
    EVENT_VISHING_CALL_ANSWERED,
    EVENT_VISHING_CALL_COMPLETED,
    EVENT_VISHING_CALL_FAILED,
    EVENT_VISHING_CALL_PLACED,
    EVENT_VISHING_TTS_PLAYED,
)


def _success_result(call_id: str = "vapi_api_test") -> dict:
    return {
        "call_control_id": call_id,
        "state": "completed",
        "call_status": "completed",
        "answered_at": "2026-11-12 12:00:05+00:00",
        # The destination rang for a plausible time before the answer, so this
        # counts as a verified human answer rather than an automatic one.
        "rang": True,
        "answer_delay_seconds": 4.2,
        "answer_suspect_auto": False,
        "ended_at": "2026-11-12 12:00:15+00:00",
        "failure_reason": None,
        "tts_media": "vcm2.api-media",
        "tts_charge": {"product": "voice_api_tts", "characters": 21},
        "hangup": {"status": "success", "message": "Call terminated."},
        "duration_seconds": 12.5,
    }


async def _create_campaign(
    db: AsyncSession,
    organization: Organization,
    template_id: uuid.UUID,
    admin_user: User,
) -> EmailCampaign:
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template_id,
        name="Real vishing test",
        channel="vishing",
        status="draft",
        total_targets=1,
        created_by=admin_user.id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def _create_tracking(
    db: AsyncSession,
    campaign: EmailCampaign,
    employee: HumanAsset,
    *,
    call_id: str = "vapi_status_test",
) -> EmailTracking:
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=campaign.template_id,
        channel="vishing",
        provider="illyvoip",
        provider_message_id=call_id,
        tracking_uuid=uuid.uuid4(),
        delivery_status="calling",
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


@pytest.mark.asyncio
async def test_place_call_requires_explicit_authorization(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=auth_headers,
        json={
            "employee_id": str(employee.id),
            "campaign_id": str(campaign.id),
            "script": "Hello from security.",
            "confirm_authorized": False,
        },
    )
    assert response.status_code == 400
    assert "confirm_authorized" in response.text


@pytest.mark.asyncio
async def test_viewer_cannot_place_a_call(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    viewer_headers: dict[str, str],
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=viewer_headers,
        json={
            "employee_id": str(employee.id),
            "script": "Hello from security.",
            "confirm_authorized": True,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_place_call_success_persists_tracking_and_ledger(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    calls: list[tuple[str, str, dict]] = []

    async def fake_place(
        self: IllyVoIPService, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        calls.append((to_phone, script_text, kwargs))
        return _success_result()

    monkeypatch.setattr(IllyVoIPService, "place_vishing_call", fake_place)

    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=auth_headers,
        json={
            "employee_id": str(employee.id),
            "campaign_id": str(campaign.id),
            "script": "Hello from security.",
            "confirm_authorized": True,
            "idempotency_key": "api-test-call-0001",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["call_control_id"] == "vapi_api_test"
    assert body["employee_id"] == str(employee.id)
    assert body["campaign_id"] == str(campaign.id)
    assert body["to_phone_masked"] == mask_phone("+966500000000")
    assert body["to_phone_masked"] != "+966500000000"
    assert body["tts_media"] == "vcm2.api-media"
    assert body["duration_seconds"] == 12.5

    tracking = await db.scalar(
        select(EmailTracking).where(
            EmailTracking.campaign_id == campaign.id,
            EmailTracking.employee_id == employee.id,
        )
    )
    assert tracking is not None
    assert tracking.provider == "illyvoip"
    assert tracking.provider_message_id == "vapi_api_test"
    assert tracking.delivery_status == "completed"
    assert tracking.sent_at is not None
    assert tracking.delivered_at is not None
    assert tracking.completed_at is not None

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id
            )
        )
    ).scalars().all()
    event_types = {row.event_type for row in interactions}
    assert EVENT_VISHING_CALL_PLACED in event_types
    assert EVENT_VISHING_CALL_ANSWERED in event_types
    assert EVENT_VISHING_TTS_PLAYED in event_types
    assert EVENT_VISHING_CALL_COMPLETED in event_types

    assert len(calls) == 1
    to_phone, script, kwargs = calls[0]
    assert to_phone == "+966500000000"
    assert script == "Hello from security."
    assert kwargs["campaign_id"] == campaign.id
    assert kwargs["tracking_uuid"] == tracking.tracking_uuid
    assert kwargs["idempotency_key"] == "api-test-call-0001"

    await db.refresh(employee)
    assert employee.total_tests_received == 1


@pytest.mark.asyncio
async def test_voice_campaign_accepts_a_real_call(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real-call ``voice`` campaign can place its call through this endpoint."""
    employee.phone = "+966500000000"
    await db.commit()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=custom_template.id,
        name="Real voice campaign",
        channel="voice",
        status="draft",
        total_targets=1,
        created_by=admin_user.id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    async def fake_place(
        self: IllyVoIPService, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        return _success_result()

    monkeypatch.setattr(IllyVoIPService, "place_vishing_call", fake_place)

    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=auth_headers,
        json={
            "employee_id": str(employee.id),
            "campaign_id": str(campaign.id),
            "script": "Hello from security.",
            "confirm_authorized": True,
            "idempotency_key": "api-test-voice-0001",
        },
    )
    assert response.status_code == 201, response.text

    tracking = await db.scalar(
        select(EmailTracking).where(
            EmailTracking.campaign_id == campaign.id,
            EmailTracking.employee_id == employee.id,
        )
    )
    assert tracking is not None
    assert tracking.channel == "voice"
    assert tracking.provider_message_id == "vapi_api_test"


@pytest.mark.asyncio
async def test_content_review_error_is_mapped_and_persisted(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )

    async def fake_place(
        self: IllyVoIPService, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        raise IllyVoIPContentReviewError(
            "This text needs a communication review.",
            review_reference="RV-API-1",
            status_code=403,
            fields={"review_reference": "RV-API-1"},
        )

    monkeypatch.setattr(IllyVoIPService, "place_vishing_call", fake_place)

    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=auth_headers,
        json={
            "employee_id": str(employee.id),
            "campaign_id": str(campaign.id),
            "script": "Hello from security.",
            "confirm_authorized": True,
        },
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error_code"] == "voice_content_review_required"
    assert detail["review_reference"] == "RV-API-1"

    tracking = await db.scalar(
        select(EmailTracking).where(
            EmailTracking.campaign_id == campaign.id,
            EmailTracking.employee_id == employee.id,
        )
    )
    assert tracking is not None
    assert tracking.delivery_status == "failed"
    assert tracking.failed_at is not None
    assert "communication review" in (tracking.delivery_error or "").lower()

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id
            )
        )
    ).scalars().all()
    assert EVENT_VISHING_CALL_FAILED in {row.event_type for row in interactions}
    await db.refresh(employee)
    assert employee.total_tests_received == 0


@pytest.mark.asyncio
async def test_manager_cannot_call_an_arbitrary_number(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = User(
        username="manager-vishing",
        email="manager-vishing@acmetest.example",
        password_hash=hash_password("Secret123!"),
        role="manager",
        organization_id=organization.id,
        is_active=True,
    )
    db.add(manager)
    await db.commit()
    await db.refresh(manager)
    token = create_access_token(str(manager.id), {"role": manager.role})
    headers = {"Authorization": f"Bearer {token}"}

    async def fake_place(
        self: IllyVoIPService, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        raise AssertionError("the provider must not be called")

    monkeypatch.setattr(IllyVoIPService, "place_vishing_call", fake_place)
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=headers,
        json={
            "to_phone": "+966500000001",
            "script": "Hello from security.",
            "confirm_authorized": True,
        },
    )
    assert response.status_code == 403
    assert "administrators" in response.text


@pytest.mark.asyncio
async def test_admin_can_place_an_ad_hoc_test_call(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_place(
        self: IllyVoIPService, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        assert to_phone == "+966500000001"
        assert kwargs["campaign_id"] is None
        assert kwargs["tracking_uuid"] is None
        return _success_result("vapi_ad_hoc")

    monkeypatch.setattr(IllyVoIPService, "place_vishing_call", fake_place)
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls",
        headers=auth_headers,
        json={
            "to_phone": "+966500000001",
            "script": "Hello from security.",
            "confirm_authorized": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["call_control_id"] == "vapi_ad_hoc"
    assert body["employee_id"] is None
    assert body["campaign_id"] is None
    assert body["tracking_uuid"] is None


@pytest.mark.asyncio
async def test_get_status_unknown_call_is_404(
    client: AsyncClient,
    organization: Organization,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/vishing/calls/vapi_missing",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_status_refreshes_tracking(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    tracking = await _create_tracking(
        db, campaign, employee, call_id="vapi_status_test"
    )

    async def fake_status(self: IllyVoIPService, call_control_id: str) -> dict:
        assert call_control_id == "vapi_status_test"
        return {
            "status": "success",
            "call_control_id": "vapi_status_test",
            "state": "completed",
            "call_status": "completed",
            "terminal": True,
            "answered_at": "2026-11-12 12:00:05+00:00",
            "ended_at": "2026-11-12 12:00:15+00:00",
            "failure_reason": None,
        }

    monkeypatch.setattr(IllyVoIPService, "get_call_status", fake_status)
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/vishing/calls/vapi_status_test",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["terminal"] is True
    assert body["state"] == "completed"

    await db.refresh(tracking)
    assert tracking.delivery_status == "completed"
    assert tracking.delivered_at is not None
    assert tracking.completed_at is not None


@pytest.mark.asyncio
async def test_hangup_refreshes_tracking(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    tracking = await _create_tracking(
        db, campaign, employee, call_id="vapi_hangup_test"
    )

    async def fake_hangup(self: IllyVoIPService, call_control_id: str) -> dict:
        assert call_control_id == "vapi_hangup_test"
        return {
            "status": "success",
            "call_control_id": "vapi_hangup_test",
            "message": "Call terminated.",
            "terminated_channels": 1,
        }

    monkeypatch.setattr(IllyVoIPService, "hangup", fake_hangup)
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/vishing/calls/"
        "vapi_hangup_test/hangup",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["terminated_channels"] == 1
    assert body["message"] == "Call terminated."

    await db.refresh(tracking)
    assert tracking.delivery_status == "completed"
    assert tracking.completed_at is not None


@pytest.mark.asyncio
async def test_voice_campaign_launch_queues_to_celery(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    campaign.channel = "voice"
    campaign.channel_config = {
        "voice": {"script": "Hello, this is the security desk."}
    }
    await db.commit()

    def fake_config(self: IllyVoIPService) -> dict:
        return {
            "provider": "illyvoip",
            "valid": True,
            "configured": True,
            "missing": [],
            "base_url": "https://api.illyvoip.com",
            "sip_user_id": "sip-test",
            "caller_id": "+966500000000",
            "caller_id_valid": True,
            "tts_language": "en-US",
            "tts_voice": "illyvoip-emma",
            "record_calls": False,
            "sandbox": False,
        }

    queued: list[str] = []

    def fake_dispatch(campaign_id: str) -> bool:
        queued.append(campaign_id)
        return True

    monkeypatch.setattr(IllyVoIPService, "configuration_status", fake_config)
    monkeypatch.setattr(
        "app.api.v1.campaigns._dispatch_to_celery", fake_dispatch
    )
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/"
        f"{campaign.id}/launch",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] is True
    assert body["sent"] == 0
    assert queued == [str(campaign.id)]


@pytest.mark.asyncio
async def test_voice_campaign_launch_blocks_when_illyvoip_missing(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    custom_template,
    admin_user: User,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee.phone = "+966500000000"
    await db.commit()
    campaign = await _create_campaign(
        db, organization, custom_template.id, admin_user
    )
    campaign.channel = "voice"
    await db.commit()

    def fake_config(self: IllyVoIPService) -> dict:
        return {
            "provider": "illyvoip",
            "valid": False,
            "configured": False,
            "missing": ["ILLYVOIP_API_KEY", "ILLYVOIP_CALLER_ID"],
            "base_url": "https://api.illyvoip.com",
            "sip_user_id": None,
            "caller_id": None,
            "caller_id_valid": False,
            "tts_language": "en-US",
            "tts_voice": "illyvoip-emma",
            "record_calls": False,
            "sandbox": False,
        }

    monkeypatch.setattr(IllyVoIPService, "configuration_status", fake_config)
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns/"
        f"{campaign.id}/launch",
        headers=auth_headers,
    )
    assert response.status_code == 502, response.text
    assert "ILLYVOIP_API_KEY" in response.text


@pytest.mark.asyncio
async def test_config_endpoint_reports_readiness(
    client: AsyncClient,
    organization: Organization,
    viewer_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_config(self: IllyVoIPService) -> dict:
        return {
            "provider": "illyvoip",
            "valid": False,
            "configured": False,
            "missing": ["ILLYVOIP_API_KEY"],
            "base_url": "https://api.illyvoip.com",
            "sip_user_id": None,
            "caller_id": None,
            "caller_id_valid": False,
            "tts_language": "en-US",
            "tts_voice": "illyvoip-emma",
            "record_calls": False,
            "sandbox": False,
        }

    monkeypatch.setattr(IllyVoIPService, "configuration_status", fake_config)
    response = await client.get(
        f"/api/v1/organizations/{organization.id}/vishing/config",
        headers=viewer_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "illyvoip"
    assert body["valid"] is False
    assert body["missing"] == ["ILLYVOIP_API_KEY"]
