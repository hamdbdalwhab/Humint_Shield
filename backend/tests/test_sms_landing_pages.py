"""SMS landing-page routing and custom-message delivery.

The resolver is pure, so these tests pin the documented priority order:
department override → manual choice → keyword detection → ``general_login``.
The launcher tests prove the resolved page travels inside the tracking link.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import EmailTemplate, EmailTracking, HumanAsset, Organization
from app.services.campaign_launcher import CampaignLauncher
from app.services.landing_page_resolver import (
    LandingPageResolver,
    detect_landing_page,
    landing_page_for_department,
    normalize_landing_page,
)
from app.services.template_personalizer import TemplatePersonalizer


def _resolver() -> LandingPageResolver:
    return LandingPageResolver()


@pytest.mark.parametrize(
    ("department", "expected"),
    [
        ("IT", "cisco_vpn"),
        ("it", "cisco_vpn"),
        ("Finance", "supplier_portal"),
        ("HR", "hr_portal"),
        ("Executive", "teams_invite"),
        ("Marketing", None),
        ("", None),
    ],
)
def test_department_landing_page(department: str, expected: str | None) -> None:
    assert landing_page_for_department(department) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Your VPN certificate expired", "cisco_vpn"),
        ("Invoice 4471 is awaiting payment", "supplier_portal"),
        ("Please sign the HR policy update", "hr_portal"),
        ("Board meeting moved — join on Teams", "teams_invite"),
        ("Reset your account password now", "microsoft_login"),
        ("Open this document today", None),
    ],
)
def test_keyword_detection(message: str, expected: str | None) -> None:
    assert detect_landing_page(message) == expected


def test_manual_choice_normalisation_and_priority() -> None:
    resolver = _resolver()
    # Manual beats keywords.
    assert (
        resolver.resolve(message="VPN certificate", manual="hr_portal") == "hr_portal"
    )
    # Department beats both.
    assert (
        resolver.resolve(message="invoice", department="IT", manual="hr_portal")
        == "cisco_vpn"
    )
    # Aliases and labels normalise to canonical slugs.
    assert normalize_landing_page("Cisco VPN") == "cisco_vpn"
    assert normalize_landing_page("m365") == "microsoft_login"
    assert normalize_landing_page("not-a-page") is None
    # Default when nothing matches.
    assert resolver.resolve(message="hello there") == "general_login"
    assert resolver.resolve_for_config(
        {"selected_landing_page": "teams_invite"}, message=None
    ) == "teams_invite"


@pytest.mark.asyncio
async def test_custom_message_reaches_textbee_with_the_resolved_page(
    db: AsyncSession,
) -> None:
    """A custom body becomes the SMS and the link carries ``?page=``."""
    organization = Organization(name="Acme Corp", domain="acme.example")
    db.add(organization)
    await db.flush()
    template = EmailTemplate(
        organization_id=organization.id,
        name="sms custom",
        subject="Notify",
        body_html="<p>Template copy</p>",
        channel="sms",
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
    )
    employee = HumanAsset(
        organization_id=organization.id,
        email="custom-sms@example.com",
        first_name="Hamed",
        last_name="Test",
        department="IT",
        phone="+967770447622",
        access_level=1,
        is_active=True,
        elo_score=1000,
    )
    db.add_all([template, employee])
    await db.commit()
    await db.refresh(template)
    await db.refresh(employee)

    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=employee.id,
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    sent: list[str] = []

    class _FakeTextBee:
        async def send_sms(self, to_phone: str, message: str) -> dict:  # noqa: ANN001
            sent.append(message)
            return {"success": True, "batch_id": "batch-custom", "error": None}

    settings = Settings(
        textbee_api_key="test-key",
        base_url="http://testserver",
        short_link_base_url="https://hument.link",
    )
    launcher = CampaignLauncher(
        personalizer=TemplatePersonalizer(settings),
        textbee_service=_FakeTextBee(),
    )

    message_id = await launcher._send_sms(
        "+967770447622",
        "Hello Hamed, your VPN session expires today: {{link}}",
        tracking,
        db,
        department=employee.department,
        manual_landing_page=None,
    )

    assert message_id == "batch-custom"
    assert sent and "VPN session expires today" in sent[0]
    assert "Template copy" not in sent[0]
    link = await db.scalar(
        select(EmailTracking).where(EmailTracking.id == tracking.id)
    )
    assert link is not None
    rows = await db.execute(
        select(EmailTracking.short_code).where(EmailTracking.id == tracking.id)
    )
    assert rows.scalar_one()


@pytest.mark.asyncio
async def test_short_link_destination_keeps_the_landing_page(
    db: AsyncSession,
) -> None:
    """``?page=cisco_vpn`` is stored on the short link destination."""
    from app.services.short_link_service import ShortLinkService

    tracking = EmailTracking(
        campaign_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        channel="sms",
        provider="textbee",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.flush()

    service = ShortLinkService(
        Settings(base_url="http://testserver", short_link_base_url="https://hument.link")
    )
    link = await service.ensure_link(db, tracking, landing_page="cisco_vpn")

    assert link.target_path == f"/sms-lure/{tracking.tracking_uuid}?page=cisco_vpn"


def test_custom_message_variables_are_rendered() -> None:
    """``{{first_name}}`` and ``{{link}}`` resolve for a custom body."""
    settings = Settings(base_url="http://testserver", short_link_base_url="https://hument.link")
    personalizer = TemplatePersonalizer(settings)

    class _Template:
        name = "sms"
        subject = "Notify"
        body_html = "<p>{{link}}</p>"
        channel = "sms"

    class _Employee:
        first_name = "Hamed"
        last_name = "Test"
        email = "h@example.com"
        department = "IT"
        job_title = "Engineer"
        is_active = True
        elo_score = 1000

    class _Organization:
        name = "Acme Corp"
        company_name = "Acme Corp"
        logo_url = None
        brand_color = None
        primary_color = None
        secondary_color = None
        domain = "acme.example"

    uid = uuid.uuid4()
    text = personalizer.render_custom_message(
        "Hi {{first_name}} — verify: {{link}}",
        _Template(),
        _Employee(),
        _Organization(),
        uid,
        "http://testserver",
        short_code="AbCdEf",
    )

    assert text.startswith("Hi Hamed")
    assert "{{" not in text
    assert "http://testserver" in text
