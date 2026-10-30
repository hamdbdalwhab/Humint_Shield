"""Quishing: poster generation, API authorization and QR scan tracking."""
from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTracking,
    Organization,
    TrainingInteraction,
)
from app.services.quishing_service import (
    DEFAULT_PRECEPT_KEY,
    QR_PIXELS,
    PosterRecipient,
    build_poster_pack,
    generate_qr_png,
    resolve_poster_copy,
)


def _recipients(count: int = 2) -> list[PosterRecipient]:
    """Return deterministic poster recipients."""
    return [
        PosterRecipient(
            name=f"موظف {index}",
            email=f"employee{index}@acme.example",
            tracking_uuid=str(uuid.uuid4()),
            tracking_url=f"http://testserver/simulation/qr/{uuid.uuid4()}",
        )
        for index in range(1, count + 1)
    ]


def _poster_organization() -> SimpleNamespace:
    """Minimal organization shape consumed by the poster renderer."""
    return SimpleNamespace(
        name="Acme Test Corporation",
        brand_primary_color="#0F6CBD",
        brand_logo_data=None,
    )


def _poster_campaign() -> SimpleNamespace:
    """Minimal campaign shape consumed by the poster renderer."""
    return SimpleNamespace(name="Quishing Awareness")


# --------------------------------------------------------------------------- #
# Service-level tests
# --------------------------------------------------------------------------- #
def test_resolve_poster_copy_uses_builtin_pretext() -> None:
    """The free-coffee lure is a real built-in Arabic pretext."""
    copy = resolve_poster_copy(
        {"qr": {"pretext_key": "free_coffee"}}, company_name="Acme"
    )
    assert copy.pretext_key == "coffee"
    assert "قهوة" in copy.headline
    assert copy.company_name == "Acme"


def test_resolve_poster_copy_custom_copy_wins() -> None:
    """Explicit campaign copy overrides the built-in pretext."""
    copy = resolve_poster_copy(
        {
            "qr": {
                "pretext_key": "hr_policy",
                "headline": "عنوان مخصص",
                "body": "نص مخصص",
                "footer": "تذييل مخصص",
            }
        },
        company_name="Acme",
    )
    assert copy.pretext_key == "hr"
    assert copy.headline == "عنوان مخصص"
    assert copy.body == "نص مخصص"
    assert copy.footer == "تذييل مخصص"


def test_resolve_poster_copy_unknown_key_falls_back() -> None:
    """An unknown pretext key never raises and falls back to the default."""
    copy = resolve_poster_copy({"qr": {"pretext_key": "does_not_exist"}})
    assert copy.pretext_key == DEFAULT_PRECEPT_KEY


def test_generate_qr_png_is_print_resolution() -> None:
    """The QR PNG is a square image capped at the documented print resolution."""
    payload = generate_qr_png("http://testserver/api/v1/track/qr/abc")
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "PNG"
        assert image.width == image.height
        assert 300 <= image.width <= QR_PIXELS
        assert image.mode == "RGB"


def test_build_poster_pack_has_one_page_per_recipient() -> None:
    """The pack is a real multi-page A4 PDF, not a placeholder."""
    recipients = _recipients(3)
    pdf = build_poster_pack(
        organization=_poster_organization(),
        campaign=_poster_campaign(),
        recipients=recipients,
        channel_config={"qr": {"pretext_key": "free_coffee"}},
        support_email="security@acme.example",
    )
    assert pdf.startswith(b"%PDF")
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert pages == 3
    assert len(pdf) > 10_000


def test_build_poster_pack_requires_a_recipient() -> None:
    """An empty recipient list is rejected instead of producing an empty PDF."""
    with pytest.raises(ValueError):
        build_poster_pack(
            organization=_poster_organization(),
            campaign=_poster_campaign(),
            recipients=[],
        )


# --------------------------------------------------------------------------- #
# API tests
# --------------------------------------------------------------------------- #
async def _create_campaign(
    client,
    auth_headers,
    organization: Organization,
    template,
    employee_ids: list[uuid.UUID],
    *,
    channel: str = "qr",
    channel_config: dict | None = None,
) -> dict:
    """Create a campaign through the public API."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "Quishing Campaign",
            "template_id": str(template.id),
            "channel": channel,
            "channel_config": channel_config or {"qr": {"pretext_key": "free_coffee"}},
            "difficulty_level": 5,
            "target_employee_ids": [str(employee_id) for employee_id in employee_ids],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_generate_qr_posters_end_to_end(
    client, db: AsyncSession, auth_headers, organization, qr_template, employees
) -> None:
    """A QR campaign produces exactly one generic poster (no employee data)."""
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        qr_template,
        [employee.id for employee in employees[:3]],
    )
    assert created["channel"] == "qr"
    assert created["channel_config"]["qr"]["pretext_key"] == "free_coffee"

    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-qr",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-poster-count"] == "1"
    assert "attachment" in response.headers["content-disposition"]
    assert "campaign-" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    pages = response.content.count(b"/Type /Page") - response.content.count(
        b"/Type /Pages"
    )
    assert pages == 1
    for employee in employees[:3]:
        assert employee.email.encode() not in response.content
        assert (employee.first_name or "").encode() not in response.content

    # The generic poster must not create per-recipient tracking rows.
    rows = (
        await db.execute(
            select(EmailTracking).where(
                EmailTracking.campaign_id == uuid.UUID(created["id"])
            )
        )
    ).scalars().all()
    assert rows == []

    campaign = await db.get(EmailCampaign, uuid.UUID(created["id"]))
    assert campaign is not None
    await db.refresh(campaign)
    assert campaign.channel_config["qr"]["pretext_key"] == "free_coffee"
    assert campaign.channel_config["qr"]["lure_type"] == "coffee"


async def test_generate_qr_posters_rejects_non_qr_campaign(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """Email campaigns cannot be turned into QR posters."""
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employees[0].id],
        channel="email",
        channel_config={},
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-qr",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "qr" in response.json()["detail"].lower()


async def test_generate_qr_posters_requires_manager(
    client, auth_headers, viewer_headers, organization, qr_template, employees
) -> None:
    """A viewer cannot download the poster."""
    created = await _create_campaign(
        client, auth_headers, organization, qr_template, [employees[0].id]
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-qr",
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_generate_qr_posters_unknown_campaign(client, auth_headers) -> None:
    """An unknown campaign id returns 404."""
    response = await client.post(
        f"/api/v1/campaigns/{uuid.uuid4()}/generate-qr",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def _seed_qr_tracking(
    db: AsyncSession, organization: Organization, employee, template
) -> EmailTracking:
    """Create a completed QR campaign and one tracking row."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="QR Scan Campaign",
        status="active",
        channel="qr",
        channel_config={"qr": {"pretext_key": "it_security"}},
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
    )
    db.add(campaign)
    await db.flush()
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        email_template_id=template.id,
        channel="qr",
        provider="simulation",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


async def test_qr_scan_redirects_without_penalty(
    client, db: AsyncSession, organization, employee, custom_template
) -> None:
    """A scan opens the mobile form and is score-neutral."""
    employee.elo_score = 1000
    await db.commit()
    tracking = await _seed_qr_tracking(db, organization, employee, custom_template)

    response = await client.get(
        f"/api/v1/track/qr/{tracking.tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/qr/hr/{tracking.tracking_uuid}"
    )
    assert "no-store" in response.headers["cache-control"]

    await db.refresh(employee)
    assert employee.elo_score == 1000

    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "qr_scanned",
            )
        )
    ).scalars().all()
    assert len(events) == 1

    second = await client.get(
        f"/api/v1/track/qr/{tracking.tracking_uuid}", follow_redirects=False
    )
    assert second.status_code == 302
    await db.refresh(employee)
    assert employee.elo_score == 1000


async def test_qr_submission_penalises_once_and_never_stores_password(
    client, db: AsyncSession, organization, employee, custom_template
) -> None:
    """The mobile form submission logs credential_submitted and -25 Elo once."""
    employee.elo_score = 1000
    await db.commit()
    tracking = await _seed_qr_tracking(db, organization, employee, custom_template)

    payload = {
        "identifier": employee.email,
        "password": "NotARealPassword-123!",
        "password_length": 20,
        "fields": {"network": "Company-WiFi-5G", "portal": "company-wifi"},
        "client": {"submit_delay_ms": 1200},
        "capture_secret": False,
    }
    first = await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}", json=payload
    )
    assert first.status_code == 200, first.text
    assert first.json()["success"] is True

    await db.refresh(employee)
    assert employee.elo_score == 975
    await db.refresh(tracking)
    assert tracking.submitted_at is not None
    assert tracking.submitted_password_encrypted is None
    assert tracking.password_length == len(payload["password"])
    assert "password" not in (tracking.submitted_fields or {})

    interactions = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "credential_submitted",
            )
        )
    ).scalars().all()
    assert len(interactions) == 1
    assert interactions[0].details["elo_delta"] == -25
    assert interactions[0].details["password_stored"] is False

    second = await client.post(
        f"/api/v1/track/submit/{tracking.tracking_uuid}", json=payload
    )
    assert second.status_code == 200
    await db.refresh(employee)
    assert employee.elo_score == 975


async def test_qr_scan_unknown_uuid_still_redirects(client) -> None:
    """An unknown UUID gives nothing away and still lands on the mobile form."""
    tracking_uuid = uuid.uuid4()
    response = await client.get(
        f"/api/v1/track/qr/{tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(f"/qr/hr/{tracking_uuid}")
