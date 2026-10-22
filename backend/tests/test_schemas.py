"""Tests for Pydantic schema (de)serialisation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    CampaignCreate,
    CampaignPublic,
    EmployeeCreate,
    EmployeePublic,
    EmailTemplatePublic,
    LoginRequest,
    TimelineEvent,
)


def test_login_request_valid() -> None:
    """Valid credentials deserialise."""
    payload = LoginRequest(username="admin", password="secret")
    assert payload.username == "admin"


def test_login_request_rejects_empty() -> None:
    """Empty usernames are rejected."""
    with pytest.raises(ValidationError):
        LoginRequest(username="", password="x")


def test_employee_create_validates_email() -> None:
    """An invalid email is rejected."""
    with pytest.raises(ValidationError):
        EmployeeCreate(email="not-an-email", first_name="Jane")


def test_employee_create_defaults() -> None:
    """Sensible defaults are applied."""
    employee = EmployeeCreate(email="a@b.example", first_name="Jane")
    assert employee.access_level == 1
    assert employee.is_active is True


def test_employee_create_rejects_bad_access_level() -> None:
    """Access level must be within 1..5."""
    with pytest.raises(ValidationError):
        EmployeeCreate(email="a@b.example", first_name="Jane", access_level=9)


def test_employee_public_coerces_decimal_score() -> None:
    """``immunity_score`` is coerced from ``Decimal`` to ``float``."""
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    public = EmployeePublic(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="a@b.example",
        first_name="A",
        last_name="B",
        access_level=1,
        immunity_score=Decimal("42.50"),
        total_tests_received=0,
        total_clicks=0,
        total_reports=0,
        total_credential_submissions=0,
        total_ignores=0,
        is_active=True,
        is_on_leave=False,
        requires_mandatory_training=False,
        under_enhanced_monitoring=False,
        created_at=now,
        updated_at=now,
    )
    assert public.immunity_score == 42.5
    assert isinstance(public.immunity_score, float)


def test_employee_public_from_orm_attributes() -> None:
    """ORM-like objects can be validated directly."""
    from types import SimpleNamespace
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    orm = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="a@b.example",
        phone=None,
        first_name="A",
        last_name="B",
        department=None,
        job_title=None,
        access_level=2,
        immunity_score=Decimal("55.00"),
        behavioral_category="hesitant",
        total_tests_received=1,
        total_clicks=0,
        total_reports=0,
        total_credential_submissions=0,
        total_ignores=0,
        last_test_date=None,
        next_test_date=None,
        is_active=True,
        is_on_leave=False,
        requires_mandatory_training=False,
        under_enhanced_monitoring=False,
        created_at=now,
        updated_at=now,
    )
    public = EmployeePublic.model_validate(orm)
    assert public.immunity_score == 55.0


def test_template_public_defaults_variables() -> None:
    """A NULL ``available_variables`` becomes an empty list."""
    now = datetime.now(timezone.utc)
    template = EmailTemplatePublic(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="T",
        subject="S",
        body_html="<p>x</p>",
        difficulty_level=5,
        available_variables=None,
        is_built_in=False,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    assert template.available_variables == []


def test_campaign_create_defaults() -> None:
    """A campaign can be created without targets."""
    campaign = CampaignCreate(name="C", template_id=uuid.uuid4())
    assert campaign.target_employee_ids == []
    assert campaign.difficulty_level == 5


def test_campaign_public_serialises_target_ids() -> None:
    """UUID target ids are serialised as strings."""
    now = datetime.now(timezone.utc)
    employee_id = uuid.uuid4()
    campaign = CampaignPublic(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        name="C",
        status="draft",
        target_employee_ids=[employee_id],
        total_targets=1,
        sent_count=0,
        failed_count=0,
        opened_count=0,
        clicked_count=0,
        completed_count=0,
        launched_at=None,
        completed_at=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )
    assert campaign.target_employee_ids == [str(employee_id)]


def test_timeline_event_serialisation() -> None:
    """Timeline events serialise with ISO timestamps."""
    event = TimelineEvent(
        event_type="email_opened", timestamp=datetime.now(timezone.utc), details={"a": 1}
    )
    dumped = event.model_dump_json()
    assert "email_opened" in dumped
