"""Campaign-launcher tests for the real IllyVoIP voice channel.

The provider is replaced with a deterministic fake, so these tests never place
a real call.  They verify the launcher's preflight, script selection, tracking
and failure semantics for ``channel='voice'``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
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
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.illyvoip_service import IllyVoIPCallFailedError
from app.services.template_service import TemplatePersonalizer
from app.services.tracking_service import EVENT_VISHING_CALL_COMPLETED


class FakeVoiceService:
    """Deterministic IllyVoIP replacement."""

    def __init__(
        self,
        *,
        valid: bool = True,
        missing: list[str] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self.valid = valid
        self.missing = missing or []
        self.raise_for = raise_for or set()
        self.calls: list[dict] = []

    def configuration_status(self) -> dict:
        return {
            "provider": "illyvoip",
            "valid": self.valid,
            "configured": self.valid,
            "missing": self.missing,
            "base_url": "https://api.illyvoip.com",
            "sip_user_id": "sip-test",
            "caller_id": "+966500000000",
            "caller_id_valid": True,
            "tts_language": "en-US",
            "tts_voice": "illyvoip-emma",
            "record_calls": False,
            "sandbox": False,
        }

    async def place_vishing_call(
        self, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        self.calls.append(
            {
                "to_phone": to_phone,
                "script": script_text,
                "kwargs": kwargs,
            }
        )
        if to_phone in self.raise_for:
            raise IllyVoIPCallFailedError(
                "The call was not answered.",
                error_code="call_not_answered",
                fields={
                    "call_control_id": f"vapi_failed_{len(self.calls)}",
                    "status": {"failure_reason": "no_answer"},
                },
            )
        return {
            "call_control_id": f"vapi_voice_{len(self.calls)}",
            "state": "completed",
            "call_status": "completed",
            "answered_at": "2026-11-12 12:00:05+00:00",
            "ended_at": "2026-11-12 12:00:15+00:00",
            "failure_reason": None,
            "tts_media": f"vcm2.media.{len(self.calls)}",
            "tts_charge": {"product": "voice_api_tts"},
            "hangup": {"status": "success"},
            "duration_seconds": 12.5,
        }


def _launcher(voice: FakeVoiceService) -> CampaignLauncher:
    settings = Settings(base_url="http://testserver", encryption_key="cd" * 32)
    return CampaignLauncher(
        email_service=object(),  # unused on the voice path
        personalizer=TemplatePersonalizer(settings),
        illyvoip_service=voice,
    )


async def _make_voice_campaign(
    db: AsyncSession,
    organization: Organization,
    template_id: uuid.UUID,
    employees: list[HumanAsset],
    *,
    script: str = "Hello, this is the security desk.",
    status: str = "draft",
) -> EmailCampaign:
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template_id,
        name="Real voice campaign",
        channel="voice",
        channel_config={"voice": {"script": script, "language": "en-US"}},
        status=status,
        target_employee_ids=[str(employee.id) for employee in employees],
        total_targets=len(employees),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@pytest.mark.asyncio
async def test_voice_campaign_places_calls_and_persists_tracking(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    targets = employees[:2]
    for index, employee in enumerate(targets):
        employee.phone = f"+96650000001{index}"
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, targets
    )
    voice = FakeVoiceService()

    result = await _launcher(voice).launch_campaign(campaign.id, db)

    assert result["total"] == 2
    assert result["sent"] == 2
    assert result["failed"] == 0
    assert len(voice.calls) == 2
    assert voice.calls[0]["script"] == "Hello, this is the security desk."
    assert voice.calls[0]["kwargs"]["campaign_id"] == campaign.id

    rows = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert row.provider == "illyvoip"
        assert row.provider_message_id.startswith("vapi_voice_")
        assert row.delivery_status == "completed"
        assert row.sent_at is not None
        assert row.delivered_at is not None
        assert row.completed_at is not None
        assert row.delivery_error is None

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.campaign_id == campaign.id
            )
        )
    ).scalars().all()
    assert EVENT_VISHING_CALL_COMPLETED in {row.event_type for row in interactions}

    await db.refresh(campaign)
    assert campaign.status == "completed"
    assert campaign.sent_count == 2


@pytest.mark.asyncio
async def test_voice_campaign_records_provider_failure(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    employee = employees[0]
    employee.phone = "+966500000099"
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, [employee]
    )
    voice = FakeVoiceService(raise_for={"+966500000099"})

    result = await _launcher(voice).launch_campaign(campaign.id, db)

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert len(voice.calls) == 1
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.provider == "illyvoip"
    assert row.provider_message_id == "vapi_failed_1"
    assert row.delivery_status == "failed"
    assert row.failed_at is not None
    assert "not answered" in (row.delivery_error or "").lower()


@pytest.mark.asyncio
async def test_voice_campaign_refuses_incomplete_configuration(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    employee = employees[0]
    employee.phone = "+966500000050"
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, [employee]
    )
    voice = FakeVoiceService(
        valid=False,
        missing=["ILLYVOIP_API_KEY", "ILLYVOIP_CALLER_ID"],
    )

    with pytest.raises(CampaignLaunchError) as excinfo:
        await _launcher(voice).launch_campaign(campaign.id, db)

    assert "VOICE delivery is not configured" in str(excinfo.value)
    assert "ILLYVOIP_API_KEY" in str(excinfo.value)
    assert voice.calls == []


@pytest.mark.asyncio
async def test_voice_campaign_rejects_target_without_phone(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    employee = employees[0]
    employee.phone = None
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, [employee]
    )
    voice = FakeVoiceService()

    result = await _launcher(voice).launch_campaign(campaign.id, db)

    assert result["sent"] == 0
    assert result["failed"] == 1
    assert voice.calls == []
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.delivery_status == "failed"
    assert "phone" in (row.delivery_error or "").lower()


@pytest.mark.asyncio
async def test_voice_script_falls_back_to_template_text(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    employee = employees[0]
    employee.phone = "+966500000060"
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, [employee], script=""
    )
    voice = FakeVoiceService()

    result = await _launcher(voice).launch_campaign(campaign.id, db)

    assert result["sent"] == 1
    assert len(voice.calls) == 1
    script = voice.calls[0]["script"]
    assert "Verify your account" in script
    assert "http://" not in script
    assert "https://" not in script


class RingingVoiceService(FakeVoiceService):
    """The handset rang for 14 seconds and the carrier then ended the call."""

    async def place_vishing_call(  # type: ignore[override]
        self, to_phone: str, script_text: str, **kwargs
    ) -> dict:
        self.calls.append({"to_phone": to_phone, "script": script_text, "kwargs": kwargs})
        raise IllyVoIPCallFailedError(
            "IllyVoIP call vapi_x ended before answer: The call could not be completed.",
            error_code="call_not_answered",
            fields={
                "call_control_id": "vapi_ringing_1",
                "rang": True,
                "ring_seconds": 14.0,
                "status": {"state": "ended", "failure_reason": "The call could not be completed."},
            },
        )


@pytest.mark.asyncio
async def test_voice_campaign_marks_unanswered_ring_as_no_answer(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    """A ring without pickup is a recipient outcome, not a delivery error."""
    employee = employees[0]
    employee.phone = "+966500000077"
    await db.commit()
    campaign = await _make_voice_campaign(
        db, organization, custom_template.id, [employee]
    )

    result = await _launcher(RingingVoiceService()).launch_campaign(campaign.id, db)

    assert result["sent"] == 0
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.delivery_status == "no_answer"
    assert row.failed_at is not None
    assert "rang" in (row.delivery_error or "")
    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.campaign_id == campaign.id
            )
        )
    ).scalars().all()
    event_types = {item.event_type for item in events}
    assert "vishing_call_not_answered" in event_types
    assert "vishing_call_failed" not in event_types


class RingOnlyVoiceService(FakeVoiceService):
    """Verification mode: rings once, then the call is cut before audio."""

    async def ring_only_call(self, to_phone: str, **kwargs) -> dict:  # type: ignore[override]
        self.calls.append({"to_phone": to_phone, "script": "", "kwargs": kwargs, "ring_only": True})
        return {
            "call_control_id": "vapi_ring_only_1",
            "rang": True,
            "ring_seconds": 9.37,
            "state": "ringing",
            "hangup": {"status": "success"},
        }


@pytest.mark.asyncio
async def test_voice_campaign_ring_only_never_speaks_or_waits_for_answer(
    db: AsyncSession,
    organization: Organization,
    employees: list[HumanAsset],
    custom_template,
) -> None:
    """Ring-only verification must not use TTS or claim an answer."""
    employee = employees[0]
    employee.phone = "+966500000066"
    await db.commit()
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=custom_template.id,
        name="Ring only",
        channel="voice",
        channel_config={"voice": {"ring_only": True}},
        status="draft",
        target_employee_ids=[str(employee.id)],
        total_targets=1,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    voice = RingOnlyVoiceService()

    result = await _launcher(voice).launch_campaign(campaign.id, db)

    assert result["sent"] == 1
    assert len(voice.calls) == 1
    assert voice.calls[0]["ring_only"] is True
    row = await db.scalar(
        select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
    )
    assert row is not None
    assert row.delivery_status == "ring_only"
    assert row.sent_at is not None
    assert row.completed_at is None
    assert row.delivery_error is None
