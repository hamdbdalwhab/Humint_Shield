"""Tests for the simulated attack-chain asset derivation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import EmailCampaign, EmailTemplate, EmailTracking
from app.services.attack_chain import build_compromised_assets


def _tracking(**kwargs) -> EmailTracking:
    """Build an unsaved tracking row with a real submission marker."""
    values = {
        "campaign_id": uuid.uuid4(),
        "employee_id": uuid.uuid4(),
        "template_id": uuid.uuid4(),
        "tracking_uuid": uuid.uuid4(),
        "submitted_at": datetime.now(timezone.utc),
        "submitted_identifier": "jane@example.com",
        "password_length": 11,
        "submitted_fields": {"office": "Cairo"},
    }
    values.update(kwargs)
    return EmailTracking(**values)


def test_no_submission_means_no_compromised_assets() -> None:
    """The reveal is only populated after a real form submission."""
    tracking = _tracking(submitted_at=None)
    assert build_compromised_assets(tracking) == []


def test_hr_template_includes_password_and_hr_files() -> None:
    """The HR pretext maps to the employee's password and HR file access."""
    tracking = _tracking()
    template = EmailTemplate(
        organization_id=uuid.uuid4(),
        name="HR Portal · Employee Records Review",
        subject="Update your employee information",
        body_html="<p>HR</p>",
        difficulty_level=4,
    )
    assets = build_compromised_assets(tracking, template)
    assert "كلمة مرور بريدك الإلكتروني" in assets
    assert "الوصول إلى ملفات الموارد البشرية" in assets
    assert "بيانات القسم ومكان العمل" in assets


def test_finance_template_maps_to_billing() -> None:
    """A finance/invoice pretext maps to the billing system."""
    tracking = _tracking(password_length=0)
    template = EmailTemplate(
        organization_id=uuid.uuid4(),
        name="Invoice overdue",
        subject="Payment required",
        body_html="<p>Invoice</p>",
        difficulty_level=5,
    )
    assets = build_compromised_assets(tracking, template)
    assert "الوصول إلى نظام الفواتير والبيانات المالية" in assets
    assert "كلمة مرور بريدك الإلكتروني" not in assets


def test_unknown_context_gets_a_generic_internal_system() -> None:
    """Without a recognizable pretext, the generic internal-system asset is used."""
    tracking = _tracking(password_length=0, submitted_fields={})
    assets = build_compromised_assets(tracking)
    assert "الوصول إلى الأنظمة الداخلية المتاحة من حسابك" in assets
    assert len(assets) == len(set(assets))
