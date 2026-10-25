"""Tests for the executive PDF report service and endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset, Organization
from app.services.executive_report import ExecutiveReportService


async def _report_fixture(db: AsyncSession, organization: Organization):
    """Create two employees and a campaign with a realistic funnel."""
    template = EmailTemplate(
        organization_id=organization.id,
        name="HR Portal · Employee Records Review",
        subject="Update your employee information",
        body_html="<p>HR</p><a href='{{tracking_url}}'>Open</a>",
        difficulty_level=4,
        is_active=True,
    )
    db.add(template)
    await db.flush()

    employees = [
        HumanAsset(
            organization_id=organization.id,
            email="risky@acmetest.example",
            first_name="Risky",
            last_name="User",
            department="Finance",
            elo_score=780,
            is_active=True,
        ),
        HumanAsset(
            organization_id=organization.id,
            email="safe@acmetest.example",
            first_name="Safe",
            last_name="User",
            department="Engineering",
            elo_score=1200,
            is_active=True,
        ),
    ]
    db.add_all(employees)
    await db.flush()

    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Executive Report Campaign",
        status="completed",
        target_employee_ids=[str(item.id) for item in employees],
        total_targets=2,
        sent_count=2,
        opened_count=2,
        clicked_count=1,
        completed_count=1,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(campaign)
    await db.flush()

    now = datetime.now(timezone.utc)
    db.add_all(
        [
            EmailTracking(
                campaign_id=campaign.id,
                employee_id=employees[0].id,
                template_id=template.id,
                tracking_uuid=uuid.uuid4(),
                sent_at=now,
                opened_at=now,
                clicked_at=now,
                submitted_at=now,
                completed_at=now,
                submitted_identifier="risky@acmetest.example",
                password_length=8,
                submitted_fields={"office": "Cairo"},
            ),
            EmailTracking(
                campaign_id=campaign.id,
                employee_id=employees[1].id,
                template_id=template.id,
                tracking_uuid=uuid.uuid4(),
                sent_at=now,
                opened_at=now,
            ),
        ]
    )
    await db.commit()
    return campaign


async def test_executive_report_generates_pdf_with_arabic_font(
    db: AsyncSession, organization: Organization
) -> None:
    """The service returns a real PDF and embeds the Arabic font."""
    campaign = await _report_fixture(db, organization)
    pdf = await ExecutiveReportService().generate(campaign, organization, db)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2_000
    assert b"Amiri" in pdf


async def test_executive_report_api_is_scoped_and_downloadable(
    client, auth_headers, viewer_headers, organization, db: AsyncSession
) -> None:
    """The endpoint returns a PDF for the caller's org and allows viewers."""
    campaign = await _report_fixture(db, organization)
    response = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    viewer_response = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}",
        headers=viewer_headers,
    )
    assert viewer_response.status_code == 200
    assert viewer_response.content.startswith(b"%PDF")


async def test_executive_report_rejects_other_organization(
    client, auth_headers, organization, db: AsyncSession
) -> None:
    """A campaign belonging to another tenant is a 404, not a data leak."""
    other = Organization(name="Other Corp", domain="other.example", industry="Finance")
    db.add(other)
    await db.flush()
    template = EmailTemplate(
        organization_id=other.id,
        name="Other template",
        subject="Other",
        body_html="<p>Other</p>",
        difficulty_level=5,
        is_active=True,
    )
    db.add(template)
    await db.flush()
    campaign = EmailCampaign(
        organization_id=other.id,
        template_id=template.id,
        name="Other campaign",
        status="completed",
        target_employee_ids=[],
        total_targets=0,
        sent_count=0,
    )
    db.add(campaign)
    await db.commit()

    response = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={campaign.id}",
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_executive_report_requires_authentication(client) -> None:
    """The report endpoint is not public."""
    response = await client.get(
        f"/api/v1/reports/executive-pdf?campaign_id={uuid.uuid4()}"
    )
    assert response.status_code == 401
