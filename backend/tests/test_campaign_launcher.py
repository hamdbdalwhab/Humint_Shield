"""Integration tests for the campaign launcher."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import EmailCampaign, EmailTracking, HumanAsset, Organization
from app.services.campaign_launcher import CampaignLaunchError, CampaignLauncher
from app.services.template_service import TemplatePersonalizer


class FakeEmailService:
    """Deterministic email transport used in place of Brevo."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.sent: list[dict] = []

    async def send_training_email(
        self, to_email: str, to_name: str, subject: str, html_content: str, correlation_id=None
    ) -> dict:  # noqa: ANN001
        """Record the message and succeed unless the recipient is blacklisted."""
        self.sent.append(
            {
                "to": to_email,
                "name": to_name,
                "subject": subject,
                "html": html_content,
                "correlation_id": correlation_id,
            }
        )
        if to_email in self.fail_for:
            return {"success": False, "message_id": None, "error": "simulated bounce"}
        return {"success": True, "message_id": f"<fake-{len(self.sent)}@brevo>", "error": None}


def _launcher(service: FakeEmailService) -> CampaignLauncher:
    settings = Settings(base_url="http://testserver", encryption_key="cd" * 32)
    return CampaignLauncher(email_service=service, personalizer=TemplatePersonalizer(settings))


async def _make_campaign(
    db: AsyncSession,
    organization: Organization,
    template_id: uuid.UUID,
    employees: list[HumanAsset],
    *,
    status: str = "draft",
) -> EmailCampaign:
    """Persist a campaign targeting ``employees``."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template_id,
        name="Launcher Campaign",
        status=status,
        target_employee_ids=[str(e.id) for e in employees],
        total_targets=len(employees),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def test_launch_success(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """A successful launch sends to every target and records tracking rows."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:3])
    service = FakeEmailService()

    result = await _launcher(service).launch_campaign(campaign.id, db)

    assert result["total"] == 3
    assert result["sent"] == 3
    assert result["failed"] == 0
    assert len(service.sent) == 3

    await db.refresh(campaign)
    assert campaign.status == "completed"
    assert campaign.launched_at is not None
    assert campaign.completed_at is not None
    assert campaign.sent_count == 3

    rows = (
        await db.execute(select(EmailTracking).where(EmailTracking.campaign_id == campaign.id))
    ).scalars().all()
    assert len(rows) == 3
    for row in rows:
        assert row.sent_at is not None
        assert row.brevo_message_id is not None
        assert row.tracking_uuid is not None


async def test_launch_personalises_each_email(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Each recipient receives their own personalised subject."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:2])
    service = FakeEmailService()

    await _launcher(service).launch_campaign(campaign.id, db)

    subjects = {message["to"]: message["subject"] for message in service.sent}
    assert f"Hello {employees[0].first_name}" in subjects[employees[0].email]
    assert f"Hello {employees[1].first_name}" in subjects[employees[1].email]


async def test_launch_tracking_url_is_unique_per_recipient(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Every recipient gets a distinct pixel/click URL."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:3])
    service = FakeEmailService()

    await _launcher(service).launch_campaign(campaign.id, db)

    pixels = []
    for message in service.sent:
        assert "/api/v1/track/open/" in message["html"]
        pixels.append(message["html"].split("/api/v1/track/open/")[1][:36])
    assert len(set(pixels)) == 3


async def test_launch_records_failures(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """A failing recipient is counted and reported without aborting the run."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:3])
    service = FakeEmailService(fail_for={employees[1].email})

    result = await _launcher(service).launch_campaign(campaign.id, db)

    assert result["sent"] == 2
    assert result["failed"] == 1
    assert result["failures"][0]["email"] == employees[1].email
    await db.refresh(campaign)
    assert campaign.status == "completed"
    assert campaign.sent_count == 2
    assert campaign.failed_count == 1


async def test_failed_send_is_not_reported_as_sent(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """A rejected send must never be stored or displayed as delivered.

    Regression: ``sent_at`` used to be written before calling Brevo, so a 401
    (e.g. an unauthorised IP) still produced a ``sent`` row in the results view.
    """
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:2])
    service = FakeEmailService(fail_for={employees[1].email})

    await _launcher(service).launch_campaign(campaign.id, db)

    rows = (
        await db.execute(select(EmailTracking).where(EmailTracking.campaign_id == campaign.id))
    ).scalars().all()
    by_employee = {row.employee_id: row for row in rows}
    rejected = by_employee[employees[1].id]
    assert rejected.sent_at is None
    assert rejected.brevo_message_id is None
    assert by_employee[employees[0].id].sent_at is not None

    data = await _launcher(service).get_campaign_results(campaign.id, db)
    assert data["stats"]["sent"] == 1
    assert data["stats"]["failed"] == 1
    statuses = {row["email"]: row["status"] for row in data["employees"]}
    assert statuses[employees[1].email] == "failed"
    assert statuses[employees[0].email] == "sent"


async def test_launch_rejects_non_draft(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Only draft campaigns can be launched."""
    campaign = await _make_campaign(
        db, organization, custom_template.id, employees[:1], status="completed"
    )
    with pytest.raises(CampaignLaunchError, match="only 'draft'"):
        await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)


async def test_launch_rejects_empty_targets(
    db: AsyncSession, organization, custom_template
) -> None:
    """A campaign with no targets cannot be launched."""
    campaign = await _make_campaign(db, organization, custom_template.id, [])
    with pytest.raises(CampaignLaunchError, match="no target"):
        await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)


async def test_launch_rejects_inactive_template(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """An inactive template blocks the launch."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    custom_template.is_active = False
    await db.commit()
    with pytest.raises(CampaignLaunchError, match="inactive"):
        await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)


async def test_launch_rejects_missing_template(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """A campaign without a template cannot be launched."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    campaign.template_id = None
    await db.commit()
    with pytest.raises(CampaignLaunchError, match="no template"):
        await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)


async def test_launch_unknown_campaign(db: AsyncSession) -> None:
    """Launching a non-existent campaign raises."""
    with pytest.raises(CampaignLaunchError, match="not found"):
        await _launcher(FakeEmailService()).launch_campaign(uuid.uuid4(), db)


async def test_launch_invalid_campaign_id(db: AsyncSession) -> None:
    """A malformed campaign id raises."""
    with pytest.raises(CampaignLaunchError, match="invalid"):
        await _launcher(FakeEmailService()).launch_campaign("not-a-uuid", db)


async def test_launch_skips_foreign_employee(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """An employee from another organization is reported as a failure."""
    other = Organization(name="Other Corp", domain="other.example")
    db.add(other)
    await db.flush()
    foreign = HumanAsset(
        organization_id=other.id,
        email="foreign@other.example",
        first_name="Foreign",
        last_name="Person",
        is_active=True,
    )
    db.add(foreign)
    await db.commit()
    await db.refresh(foreign)

    campaign = await _make_campaign(
        db, organization, custom_template.id, employees[:1] + [foreign]
    )
    result = await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)
    assert result["sent"] == 1
    assert result["failed"] == 1


async def test_launch_skips_inactive_employee(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Inactive employees are not emailed."""
    employees[0].is_active = False
    await db.commit()
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    result = await _launcher(FakeEmailService()).launch_campaign(campaign.id, db)
    assert result["sent"] == 0
    assert result["failed"] == 1


async def test_launch_does_not_resend_existing_tracking(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """A pre-existing tracking row with ``sent_at`` is treated as already sent."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    from datetime import datetime, timezone

    db.add(
        EmailTracking(
            campaign_id=campaign.id,
            employee_id=employees[0].id,
            email_template_id=custom_template.id,
            tracking_uuid=uuid.uuid4(),
            sent_at=datetime.now(timezone.utc),
            brevo_message_id="<pre-existing@brevo>",
        )
    )
    await db.commit()
    service = FakeEmailService()

    result = await _launcher(service).launch_campaign(campaign.id, db)
    assert result["sent"] == 1
    assert service.sent == []


async def test_get_campaign_results(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Results aggregate engagement and derive per-employee status."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:2])
    launcher = _launcher(FakeEmailService())
    await launcher.launch_campaign(campaign.id, db)

    # Simulate one open and one click.
    from app.services.tracking_service import TrackingService

    rows = (
        await db.execute(
            select(EmailTracking).where(EmailTracking.campaign_id == campaign.id)
        )
    ).scalars().all()
    tracking_service = TrackingService()
    await tracking_service.log_open(str(rows[0].tracking_uuid), "1.2.3.4", "UA", db)
    await tracking_service.log_click(str(rows[1].tracking_uuid), "1.2.3.4", "UA", db)
    await db.commit()

    data = await launcher.get_campaign_results(campaign.id, db)
    assert data["stats"]["total"] == 2
    assert data["stats"]["sent"] == 2
    assert data["stats"]["opened"] == 2  # click implies open
    assert data["stats"]["clicked"] == 1
    assert data["stats"]["open_rate"] == 100.0
    statuses = {row["email"]: row["status"] for row in data["employees"]}
    assert set(statuses.values()) == {"opened", "clicked"}
    assert len(data["employees"]) == 2


async def test_get_campaign_results_unknown(db: AsyncSession) -> None:
    """Results for an unknown campaign raise."""
    with pytest.raises(CampaignLaunchError):
        await _launcher(FakeEmailService()).get_campaign_results(uuid.uuid4(), db)


async def test_get_campaign_results_empty(db: AsyncSession, organization, employees, custom_template) -> None:
    """A draft campaign with no sends still reports sane zeroed stats."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    data = await _launcher(FakeEmailService()).get_campaign_results(campaign.id, db)
    assert data["stats"]["sent"] == 0
    assert data["stats"]["open_rate"] == 0.0
    assert data["employees"] == []


async def test_launch_tolerates_duplicate_target_ids(
    db: AsyncSession, organization, employees, custom_template
) -> None:
    """Duplicate target ids are de-duplicated by the launcher loop guard."""
    campaign = await _make_campaign(db, organization, custom_template.id, employees[:1])
    campaign.target_employee_ids = [str(employees[0].id), str(employees[0].id)]
    await db.commit()
    service = FakeEmailService()
    result = await _launcher(service).launch_campaign(campaign.id, db)
    # The second pass finds the existing tracking row and does not resend.
    assert result["sent"] == 2
    assert len(service.sent) == 1
