"""Safe USB-drop PDF generation, authorization and open tracking."""
from __future__ import annotations

import io
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTracking,
    Organization,
    TrainingInteraction,
)
from app.services.usb_drop_service import (
    DEFAULT_DOCUMENT_NAME,
    HTML_DOCUMENT_NAME,
    USB_HTML_WARNING,
    USB_WARNING,
    USBDropRecipient,
    build_usb_drop_pack,
    build_usb_html,
    content_disposition,
    content_disposition_html,
    resolve_usb_copy,
    safe_document_name,
    safe_html_name,
)


def _recipients(count: int = 2) -> list[USBDropRecipient]:
    """Return deterministic USB-document recipients."""
    return [
        USBDropRecipient(
            name=f"موظف {index}",
            email=f"employee{index}@acme.example",
            tracking_uuid=str(uuid.uuid4()),
            tracking_url=f"http://testserver/api/v1/track/usb/{uuid.uuid4()}",
            department="المالية",
        )
        for index in range(1, count + 1)
    ]


def _usb_organization() -> SimpleNamespace:
    """Minimal organization shape consumed by the USB renderer."""
    return SimpleNamespace(
        name="Acme Test Corporation",
        brand_primary_color="#0E7490",
        brand_logo_data=None,
    )


def _usb_campaign() -> SimpleNamespace:
    return SimpleNamespace(name="USB Drop Exercise")


def test_resolve_usb_copy_uses_the_required_document_name() -> None:
    """The default document is the Arabic salary lure, with a PDF extension."""
    copy = resolve_usb_copy(None)
    assert copy.document_name == DEFAULT_DOCUMENT_NAME
    assert copy.document_name.endswith(".pdf")
    assert copy.month_label


def test_safe_document_name_blocks_path_traversal() -> None:
    """Operator-supplied names cannot inject a path or a header newline."""
    assert "/" not in safe_document_name("../../etc/passwd.pdf")
    assert "\\" not in safe_document_name("..\\..\\evil.pdf")
    assert "\n" not in safe_document_name("line\r\nbreak.pdf")
    assert safe_document_name("custom").endswith(".pdf")


def test_content_disposition_encodes_the_arabic_name() -> None:
    """The download header carries the Arabic name through RFC 5987."""
    header = content_disposition(DEFAULT_DOCUMENT_NAME)
    assert "attachment" in header
    assert "filename*=UTF-8''" in header
    assert "%D8%B1" in header  # the Arabic letter reh


def test_build_usb_drop_pack_has_one_page_per_recipient() -> None:
    """The pack is a real multi-page A4 PDF, not a placeholder."""
    pdf = build_usb_drop_pack(
        organization=_usb_organization(),
        campaign=_usb_campaign(),
        recipients=_recipients(3),
        channel_config={"usb": {"document_name": DEFAULT_DOCUMENT_NAME}},
        support_email="security@acme.example",
    )
    assert pdf.startswith(b"%PDF")
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert pages == 3
    assert len(pdf) > 10_000
    assert b"/JavaScript" not in pdf
    assert b"/Launch" not in pdf
    assert b"/EmbeddedFile" not in pdf


def test_build_usb_drop_pack_requires_a_recipient() -> None:
    """An empty recipient list is rejected instead of producing an empty PDF."""
    with pytest.raises(ValueError):
        build_usb_drop_pack(
            organization=_usb_organization(),
            campaign=_usb_campaign(),
            recipients=[],
        )


def test_usb_warning_is_the_required_arabic_message() -> None:
    """The exact teachable moment is fixed in the renderer."""
    assert "لقد قمت بتوصيل فلاشة مجهولة" in USB_WARNING
    assert "اختباراً أمنياً" in USB_WARNING
    assert "كان بإمكان هذا الملف تدمير جهازك" in USB_WARNING


def test_build_usb_html_is_safe_and_contains_the_exact_warning() -> None:
    """The HTML artefact is inert, reports once and shows the required warning."""
    recipient = _recipients(1)[0]
    html_bytes = build_usb_html(
        organization=_usb_organization(),
        recipient=recipient,
        training_url=f"http://testserver/training/{recipient.tracking_uuid}?channel=usb",
        support_email="security@acme.example",
    )
    document = html_bytes.decode("utf-8")
    assert document.startswith("<!doctype html>")
    assert USB_HTML_WARNING in document
    assert recipient.tracking_url in document
    assert 'mode: "no-cors"' in document
    assert "fetch(trackingUrl" in document
    assert "<form" not in document.lower()
    assert "<input" not in document.lower()
    assert "eval(" not in document
    assert "document.cookie" not in document
    assert "ActiveXObject" not in document
    assert ".exe" not in document.lower()
    assert ".bat" not in document.lower()


def test_html_document_name_is_exact_and_header_safe() -> None:
    """The HTML deliverable uses the required Arabic filename."""
    assert safe_html_name(HTML_DOCUMENT_NAME) == HTML_DOCUMENT_NAME
    assert "/" not in safe_html_name("../../evil.html")
    assert "\n" not in safe_html_name("line\r\nbreak.html")
    header = content_disposition_html()
    assert "attachment" in header
    assert "filename*=UTF-8''" in header
    assert "%D8%A7" in header  # the Arabic letter alef


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
    channel: str = "usb",
    channel_config: dict | None = None,
) -> dict:
    """Create a campaign through the public API."""
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/email-campaigns",
        json={
            "name": "USB Drop Campaign",
            "template_id": str(template.id),
            "channel": channel,
            "channel_config": channel_config
            if channel_config is not None
            else {"usb": {"document_name": DEFAULT_DOCUMENT_NAME}},
            "difficulty_level": 5,
            "target_employee_ids": [str(employee_id) for employee_id in employee_ids],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_generate_usb_pdf_end_to_end(
    client, db: AsyncSession, auth_headers, organization, custom_template, employees
) -> None:
    """A USB campaign produces one document per recipient and unique tracking rows."""
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employee.id for employee in employees[:3]],
    )
    assert created["channel"] == "usb"
    assert created["channel_config"]["usb"]["document_name"] == DEFAULT_DOCUMENT_NAME

    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-pdf",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-document-count"] == "3"
    assert "attachment" in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    rows = (
        await db.execute(
            select(EmailTracking).where(
                EmailTracking.campaign_id == uuid.UUID(created["id"])
            )
        )
    ).scalars().all()
    assert len(rows) == 3
    assert {row.channel for row in rows} == {"usb"}
    assert {row.provider for row in rows} == {"simulation"}
    assert len({row.tracking_uuid for row in rows}) == 3

    campaign = await db.get(EmailCampaign, uuid.UUID(created["id"]))
    assert campaign is not None
    await db.refresh(campaign)
    assert campaign.channel_config["usb"]["document_name"] == DEFAULT_DOCUMENT_NAME


async def test_generate_usb_pdf_single_recipient(
    client, db: AsyncSession, auth_headers, organization, custom_template, employees
) -> None:
    """The optional employee filter prepares one physical USB drive."""
    selected = employees[0]
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employee.id for employee in employees[:3]],
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-pdf",
        params={"employee_id": str(selected.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-document-count"] == "1"
    rows = (
        await db.execute(
            select(EmailTracking).where(
                EmailTracking.campaign_id == uuid.UUID(created["id"])
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].employee_id == selected.id


async def test_generate_usb_pdf_rejects_non_usb_campaign(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """Email/QR campaigns cannot be turned into USB documents."""
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employees[0].id],
        channel="qr",
        channel_config={"qr": {"pretext_key": "it_security"}},
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-pdf",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "usb" in response.json()["detail"].lower()


async def test_generate_usb_pdf_requires_manager(
    client, auth_headers, viewer_headers, organization, custom_template, employees
) -> None:
    """A viewer cannot download the USB document pack."""
    created = await _create_campaign(
        client, auth_headers, organization, custom_template, [employees[0].id]
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-pdf",
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def test_generate_usb_pdf_unknown_campaign(client, auth_headers) -> None:
    """An unknown campaign id returns 404."""
    response = await client.post(
        f"/api/v1/campaigns/{uuid.uuid4()}/generate-usb-pdf",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_generate_usb_html_single_recipient(
    client, db: AsyncSession, auth_headers, organization, custom_template, employees
) -> None:
    """A single target receives the exact Arabic HTML filename and warning."""
    selected = employees[0]
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employee.id for employee in employees[:3]],
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-html",
        params={"employee_id": str(selected.id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-document-count"] == "1"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition
    document = response.content.decode("utf-8")
    assert document.startswith("<!doctype html>")
    assert USB_HTML_WARNING in document
    assert "/api/v1/track/usb/" in document
    assert "fetch(trackingUrl" in document
    assert "<input" not in document.lower()
    assert "<form" not in document.lower()

    rows = (
        await db.execute(
            select(EmailTracking).where(
                EmailTracking.campaign_id == uuid.UUID(created["id"])
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].employee_id == selected.id
    assert str(rows[0].tracking_uuid) in document


async def test_generate_usb_html_multiple_recipients_returns_zip(
    client, auth_headers, organization, custom_template, employees
) -> None:
    """Multiple recipients are packaged so every drive keeps a unique identity."""
    created = await _create_campaign(
        client,
        auth_headers,
        organization,
        custom_template,
        [employee.id for employee in employees[:3]],
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-html",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-document-count"] == "3"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == 3
        assert all(name.endswith("/الرواتب_السرية.html") for name in names)
        assert len(set(names)) == 3
        first = archive.read(names[0]).decode("utf-8")
        assert USB_HTML_WARNING in first
        assert "/api/v1/track/usb/" in first


async def test_generate_usb_html_requires_manager(
    client, auth_headers, viewer_headers, organization, custom_template, employees
) -> None:
    """A viewer cannot download the HTML payload."""
    created = await _create_campaign(
        client, auth_headers, organization, custom_template, [employees[0].id]
    )
    response = await client.post(
        f"/api/v1/campaigns/{created['id']}/generate-usb-html",
        headers=viewer_headers,
    )
    assert response.status_code == 403


async def _seed_usb_tracking(
    db: AsyncSession,
    organization: Organization,
    employee,
    template,
    *,
    channel: str = "usb",
) -> EmailTracking:
    """Create a campaign and one tracking row for the USB open endpoint."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="USB Open Campaign",
        status="active",
        channel=channel,
        channel_config={"usb": {"document_name": DEFAULT_DOCUMENT_NAME}},
        target_employee_ids=[str(employee.id)],
        total_targets=1,
        sent_count=1,
    )
    db.add(campaign)
    await db.flush()
    tracking = EmailTracking(
        campaign_id=campaign.id,
        employee_id=employee.id,
        template_id=template.id,
        channel=channel,
        provider="simulation",
        tracking_uuid=uuid.uuid4(),
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


async def test_usb_open_redirects_and_penalises_once(
    client, db: AsyncSession, organization, employee, custom_template
) -> None:
    """A first open costs 30 Elo and redirects to the USB training page."""
    employee.elo_score = 1000
    await db.commit()
    tracking = await _seed_usb_tracking(db, organization, employee, custom_template)

    response = await client.get(
        f"/api/v1/track/usb/{tracking.tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/training/{tracking.tracking_uuid}?channel=usb"
    )
    assert "no-store" in response.headers["cache-control"]

    await db.refresh(employee)
    assert employee.elo_score == 970

    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "usb_opened",
            )
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].details["first_open"] is True
    assert events[0].details["elo_delta"] == -30

    second = await client.get(
        f"/api/v1/track/usb/{tracking.tracking_uuid}", follow_redirects=False
    )
    assert second.status_code == 302
    await db.refresh(employee)
    assert employee.elo_score == 970
    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "usb_opened",
            )
        )
    ).scalars().all()
    assert len(events) == 2


async def test_usb_open_channel_mismatch_does_not_penalise(
    client, db: AsyncSession, organization, employee, custom_template
) -> None:
    """A QR tracking row cannot be penalised through the USB endpoint."""
    employee.elo_score = 1000
    await db.commit()
    tracking = await _seed_usb_tracking(
        db, organization, employee, custom_template, channel="qr"
    )

    response = await client.get(
        f"/api/v1/track/usb/{tracking.tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/training/{tracking.tracking_uuid}?channel=qr"
    )
    await db.refresh(employee)
    assert employee.elo_score == 1000
    events = (
        await db.execute(
            select(TrainingInteraction).where(
                TrainingInteraction.tracking_id == tracking.id,
                TrainingInteraction.event_type == "usb_opened",
            )
        )
    ).scalars().all()
    assert events == []


async def test_usb_open_unknown_uuid_still_redirects(client) -> None:
    """An invalid UUID redirects to the safe training page without a DB write."""
    tracking_uuid = uuid.uuid4()
    response = await client.get(
        f"/api/v1/track/usb/{tracking_uuid}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(
        f"/training/{tracking_uuid}?channel=usb"
    )
