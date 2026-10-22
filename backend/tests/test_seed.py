"""Tests for seed data and diagnostics endpoints."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailTemplate, HumanAsset, Organization, TrainingModule, User
from app.services.seed import (
    BUILT_IN_TEMPLATES,
    ensure_bootstrap_data,
    seed_builtin_templates,
    seed_demo_employees,
    seed_training_modules,
)


async def test_eight_builtin_templates_defined() -> None:
    """Exactly eight built-in templates are defined."""
    assert len(BUILT_IN_TEMPLATES) == 8


async def test_required_templates_present() -> None:
    """The eight required template names are present."""
    names = {template["name"] for template in BUILT_IN_TEMPLATES}
    assert names == {
        "Urgent Password Change",
        "Message from Direct Manager",
        "Suspicious Login Alert",
        "HR Data Update Required",
        "Overdue Invoice",
        "Employee Bonus Announcement",
        "Emergency Meeting Notice",
        "Mandatory Software Update",
    }


async def test_every_template_has_tracking_link() -> None:
    """Every built-in template contains a tracked call to action."""
    for template in BUILT_IN_TEMPLATES:
        assert "{{tracking_url}}" in template["body_html"]
        assert template["subject"]
        assert 1 <= template["difficulty_level"] <= 10


async def test_seed_builtin_templates_is_idempotent(
    db: AsyncSession, organization: Organization
) -> None:
    """Seeding twice does not duplicate templates."""
    first = await seed_builtin_templates(db, organization.id)
    await db.commit()
    second = await seed_builtin_templates(db, organization.id)
    await db.commit()
    assert first == 8
    assert second == 0
    count = await db.scalar(
        select(func.count(EmailTemplate.id)).where(EmailTemplate.organization_id == organization.id)
    )
    assert count == 8


async def test_seed_training_modules_idempotent(
    db: AsyncSession, organization: Organization
) -> None:
    """Training modules are seeded once."""
    assert await seed_training_modules(db, organization.id) == 4
    await db.commit()
    assert await seed_training_modules(db, organization.id) == 0


async def test_seed_demo_employees_idempotent(
    db: AsyncSession, organization: Organization
) -> None:
    """Demo employees are seeded once."""
    assert await seed_demo_employees(db, organization) == 5
    await db.commit()
    assert await seed_demo_employees(db, organization) == 0


async def test_phone_is_encrypted_at_rest(
    db: AsyncSession, organization: Organization
) -> None:
    """The ``phone`` column stores ciphertext, not plaintext."""
    from sqlalchemy import text

    employee = HumanAsset(
        organization_id=organization.id,
        email="enc@acmetest.example",
        first_name="Enc",
        last_name="Test",
        phone="+1-555-0100",
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    assert employee.phone == "+1-555-0100"

    raw = await db.execute(
        text("SELECT phone FROM human_assets WHERE email = :email"), {"email": "enc@acmetest.example"}
    )
    stored = raw.scalar_one()
    assert stored is not None
    assert stored.startswith("enc:v1:")
    assert "+1-555-0100" not in stored


async def test_ensure_bootstrap_data_creates_everything(db: AsyncSession) -> None:
    """Bootstrap creates the org, admin, templates and modules."""
    summary = await ensure_bootstrap_data(db)
    assert summary["templates_created"] == 8
    assert summary["modules_created"] == 4

    org_count = await db.scalar(select(func.count(Organization.id)))
    user_count = await db.scalar(select(func.count(User.id)))
    template_count = await db.scalar(select(func.count(EmailTemplate.id)))
    module_count = await db.scalar(select(func.count(TrainingModule.id)))
    assert org_count == 1
    assert user_count == 1
    assert template_count == 8
    assert module_count == 4


async def test_ensure_bootstrap_data_is_idempotent(db: AsyncSession) -> None:
    """Bootstrap is safe to run on every startup."""
    await ensure_bootstrap_data(db)
    summary = await ensure_bootstrap_data(db)
    assert summary["templates_created"] == 0
    org_count = await db.scalar(select(func.count(Organization.id)))
    assert org_count == 1


# --------------------------------------------------------------------------- #
# Diagnostics endpoints
# --------------------------------------------------------------------------- #
async def test_health_endpoint(client, auth_headers) -> None:
    """The health endpoint reports dependency status."""
    response = await client.get("/api/v1/test/health", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"]["ok"] is True
    assert "brevo_configured" in body


async def test_config_endpoint(client, auth_headers) -> None:
    """The config endpoint exposes non-secret settings."""
    response = await client.get("/api/v1/test/config", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["base_url"]
    assert body["from_email"]


async def test_brevo_test_endpoint(client, auth_headers, monkeypatch) -> None:
    """The Brevo test endpoint returns the transport result."""
    from app.services.brevo_email_service import BrevoEmailService

    async def _fake_send(self, to_email: str) -> dict:  # noqa: ANN001
        return {"success": True, "message_id": "<test@brevo>", "error": None}

    monkeypatch.setattr(BrevoEmailService, "send_test_email", _fake_send)
    response = await client.post(
        "/api/v1/test/brevo", json={"to_email": "me@acmetest.example"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_brevo_verify_endpoint(client, auth_headers, monkeypatch) -> None:
    """The verify endpoint reports an unconfigured key."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "email_dry_run", False)
    response = await client.get("/api/v1/test/brevo/verify", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["valid"] is False


async def test_diagnostics_require_privilege(client, viewer_headers) -> None:
    """A viewer can read health but cannot send test email."""
    assert (await client.get("/api/v1/test/health", headers=viewer_headers)).status_code == 200
    response = await client.post(
        "/api/v1/test/brevo", json={"to_email": "x@y.example"}, headers=viewer_headers
    )
    assert response.status_code == 403


async def test_metrics_endpoint(client) -> None:
    """Prometheus metrics are exposed."""
    response = await client.get("/metrics")
    assert response.status_code == 200
