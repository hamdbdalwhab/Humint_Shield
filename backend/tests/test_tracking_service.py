"""Tests for the tracking service (open/click/complete + double-count guards)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailCampaign,
    EmailTemplate,
    EmailTracking,
    HumanAsset,
    Organization,
    TrainingInteraction,
)
from app.services.tracking_service import (
    TrackingService,
    decrypt_payload,
    encrypt_payload,
    normalize_submitted_values,
    sanitize_submitted_fields,
)


async def _make_tracking(
    db: AsyncSession,
    organization: Organization,
    employee: HumanAsset,
    template: EmailTemplate,
) -> EmailTracking:
    """Create a campaign + tracking row and return the tracking row."""
    campaign = EmailCampaign(
        organization_id=organization.id,
        template_id=template.id,
        name="Tracking Campaign",
        status="completed",
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
        tracking_uuid=uuid.uuid4(),
        sent_at=None,
    )
    db.add(tracking)
    await db.commit()
    await db.refresh(tracking)
    return tracking


async def test_log_open_sets_timestamp_and_increments(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The first open sets ``opened_at`` and increments the campaign counter."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    row = await service.log_open(str(tracking.tracking_uuid), "203.0.113.5", "TestAgent/1.0", db)
    await db.commit()

    assert row is not None
    assert row.opened_at is not None
    assert row.open_count == 1
    assert row.last_ip_address == "203.0.113.5"
    assert row.last_user_agent == "TestAgent/1.0"

    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.opened_count == 1


async def test_repeated_opens_increment_open_count_only(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Subsequent opens bump ``open_count`` but not the campaign counter."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    await service.log_open(str(tracking.tracking_uuid), "203.0.113.5", "UA", db)
    await db.commit()
    await service.log_open(str(tracking.tracking_uuid), "203.0.113.6", "UA", db)
    await db.commit()

    await db.refresh(tracking)
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert tracking.open_count == 2
    assert campaign.opened_count == 1


async def test_log_open_unknown_uuid_returns_none(db: AsyncSession) -> None:
    """An unknown tracking UUID is a no-op."""
    assert await TrackingService().log_open(str(uuid.uuid4()), "1.2.3.4", "UA", db) is None


async def test_log_open_invalid_uuid_returns_none(db: AsyncSession) -> None:
    """A non-UUID identifier is rejected without touching the database."""
    assert await TrackingService().log_open("not-a-uuid", "1.2.3.4", "UA", db) is None


async def test_log_click_penalises_employee(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """A click sets ``clicked_at``, increments counters and lowers the score."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    starting_score = float(employee.immunity_score)
    service = TrackingService()

    row = await service.log_click(str(tracking.tracking_uuid), "198.51.100.9", "UA", db)
    await db.commit()

    assert row is not None
    assert row.clicked_at is not None
    assert row.click_count == 1
    # A click also counts as an open.
    assert row.opened_at is not None

    await db.refresh(employee)
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.clicked_count == 1
    assert campaign.opened_count == 1
    assert employee.total_clicks == 1
    # The classification engine re-derives the score from the 90-day window.
    assert float(employee.immunity_score) < starting_score


async def test_repeated_clicks_do_not_double_count(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The campaign ``clicked_count`` only increments once."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    for _ in range(3):
        await service.log_click(str(tracking.tracking_uuid), "198.51.100.9", "UA", db)
        await db.commit()

    await db.refresh(tracking)
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert tracking.click_count == 3
    assert campaign.clicked_count == 1
    await db.refresh(employee)
    assert employee.total_clicks == 1


async def test_log_click_unknown_uuid(db: AsyncSession) -> None:
    """Unknown click identifiers are ignored."""
    assert await TrackingService().log_click(str(uuid.uuid4()), "1.1.1.1", "UA", db) is None


async def test_log_completion_sets_timestamp_and_bonus(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Completion sets the timestamp and awards the awareness bonus."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    await service.log_click(str(tracking.tracking_uuid), "198.51.100.9", "UA", db)
    await db.commit()
    await db.refresh(employee)
    after_click = float(employee.immunity_score)

    row = await service.log_completion(str(tracking.tracking_uuid), db)
    await db.commit()

    assert row is not None
    assert row.completed_training_at is not None
    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.completed_count == 1
    await db.refresh(employee)
    assert float(employee.immunity_score) >= after_click


async def test_completion_is_idempotent(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Completing twice does not increment the campaign counter twice."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    await service.log_completion(str(tracking.tracking_uuid), db)
    await db.commit()
    await service.log_completion(str(tracking.tracking_uuid), db)
    await db.commit()

    campaign = await db.get(EmailCampaign, tracking.campaign_id)
    assert campaign.completed_count == 1


async def test_log_completion_unknown_uuid(db: AsyncSession) -> None:
    """Unknown completion identifiers are ignored."""
    assert await TrackingService().log_completion(str(uuid.uuid4()), db) is None


async def test_status_property_progression(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The derived status advances sent -> opened -> clicked -> completed."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    assert tracking.status == "pending"

    service = TrackingService()
    from datetime import datetime, timezone

    tracking.sent_at = datetime.now(timezone.utc)
    assert tracking.status == "sent"

    await service.log_open(str(tracking.tracking_uuid), "1.2.3.4", "UA", db)
    await db.commit()
    await db.refresh(tracking)
    assert tracking.status == "opened"

    await service.log_click(str(tracking.tracking_uuid), "1.2.3.4", "UA", db)
    await db.commit()
    await db.refresh(tracking)
    assert tracking.status == "clicked"

    await service.log_submission(
        str(tracking.tracking_uuid), "jane@acmetest.example", None, 9, {}, "1.2.3.4", "UA", db
    )
    await db.commit()
    await db.refresh(tracking)
    assert tracking.status == "submitted"

    await service.log_completion(str(tracking.tracking_uuid), db)
    await db.commit()
    await db.refresh(tracking)
    assert tracking.status == "completed"


@pytest.mark.parametrize("uuid_value", [uuid.uuid4(), str(uuid.uuid4())])
async def test_uuid_coercion_accepts_both_types(uuid_value) -> None:
    """Both ``UUID`` objects and strings are accepted."""
    assert TrackingService._coerce_uuid(uuid_value) is not None
    assert TrackingService._coerce_uuid("garbage") is None
    assert TrackingService._coerce_uuid(None) is None


# --------------------------------------------------------------------------- #
# Simulated credential form
# --------------------------------------------------------------------------- #
def test_sanitize_submitted_fields_drops_secret_looking_keys() -> None:
    """Password-like keys are dropped whatever their spelling."""
    clean = sanitize_submitted_fields(
        {
            "department": "Finance",
            "password": "hunter2",
            "PASSWORD": "hunter2",
            "user_password": "hunter2",
            "api-token": "abc",
            "one_time_otp": "123456",
            "pin": "1234",
            "note": "x" * 900,
            "empty": None,
        }
    )
    assert clean["department"] == "Finance"
    for dropped in (
        "password",
        "PASSWORD",
        "user_password",
        "api-token",
        "one_time_otp",
        "pin",
        "empty",
    ):
        assert dropped not in clean
    assert len(clean["note"]) == 512


def test_sanitize_submitted_fields_rejects_junk_and_caps_size() -> None:
    """Non-mappings are ignored and the field count is capped."""
    assert sanitize_submitted_fields(None) == {}
    assert sanitize_submitted_fields(["a", "b"]) == {}
    assert len(sanitize_submitted_fields({f"field{i}": "v" for i in range(60)})) == 25


async def test_mark_form_viewed_is_idempotent(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The first render is timestamped; every render lands in the ledger."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    assert tracking.form_viewed_at is None
    await service.mark_form_viewed(str(tracking.tracking_uuid), db)
    await db.commit()
    await db.refresh(tracking)
    first = tracking.form_viewed_at
    assert first is not None

    await service.mark_form_viewed(str(tracking.tracking_uuid), db)
    await db.commit()
    await db.refresh(tracking)
    assert tracking.form_viewed_at == first

    from sqlalchemy import func, select

    views = await db.scalar(
        select(func.count(TrainingInteraction.id)).where(
            TrainingInteraction.tracking_id == tracking.id,
            TrainingInteraction.event_type == "form_viewed",
        )
    )
    assert views == 2


async def test_mark_form_viewed_unknown_uuid(db: AsyncSession) -> None:
    """An unknown UUID is a no-op."""
    assert await TrackingService().mark_form_viewed(str(uuid.uuid4()), db) is None


async def test_log_submission_unknown_and_invalid_uuid(db: AsyncSession) -> None:
    """Unknown or malformed identifiers never raise."""
    service = TrackingService()
    assert (
        await service.log_submission(str(uuid.uuid4()), "a@b.c", None, 4, {}, None, None, db)
        is None
    )
    assert (
        await service.log_submission("not-a-uuid", "a@b.c", None, 4, {}, None, None, db) is None
    )


async def test_log_submission_records_every_typed_value_encrypted(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Every typed value is stored, secrets included, but only encrypted."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    row = await TrackingService().log_submission(
        str(tracking.tracking_uuid),
        "someone@acmetest.example",
        "Leak-Value-99",
        None,
        {"password": "Leak-Value-99", "office": "Cairo"},
        "9.9.9.9",
        "UA",
        db,
    )
    await db.commit()
    await db.refresh(tracking)

    assert row is not None
    assert tracking.form_submitted_at is not None
    assert tracking.submission_count == 1
    assert tracking.submitted_identifier == "someone@acmetest.example"
    # Length is derived from the value that arrived.
    assert tracking.password_length == len("Leak-Value-99")
    # The convenience snapshot stays secret-free…
    assert tracking.submitted_fields == {"office": "Cairo"}
    # …while the complete payload is captured and encrypted.
    assert tracking.submitted_password_encrypted is not None
    assert tracking.submitted_password_encrypted.startswith("enc:v1:")
    assert "Leak-Value-99" not in tracking.submitted_password_encrypted
    assert tracking.submitted_payload_encrypted is not None
    assert tracking.submitted_payload_encrypted.startswith("enc:v1:")
    assert "Leak-Value-99" not in tracking.submitted_payload_encrypted
    assert decrypt_payload(tracking.submitted_payload_encrypted) == {
        "identifier": "someone@acmetest.example",
        "password": "Leak-Value-99",
        "office": "Cairo",
    }
    assert tracking.last_ip_address == "9.9.9.9"


async def test_log_simulation_report_unknown_and_invalid_uuid(db: AsyncSession) -> None:
    """Reporting with an unknown identifier never raises."""
    service = TrackingService()
    assert await service.log_simulation_report(str(uuid.uuid4()), None, None, db) is None
    assert await service.log_simulation_report("garbage", None, None, db) is None


async def test_log_simulation_report_is_idempotent(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Only the first report creates an inbox entry."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    first = await service.log_simulation_report(str(tracking.tracking_uuid), "1.1.1.1", "UA", db)
    await db.commit()
    assert first is not None

    await db.refresh(tracking)
    assert tracking.reported_at is not None

    second = await service.log_simulation_report(str(tracking.tracking_uuid), "1.1.1.1", "UA", db)
    await db.commit()
    assert second is None


async def test_direct_form_submission_backfills_engagement_at_form_time(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """A direct form submission never lands after the form view it followed.

    Recipients who reach the training page without the pixel or the click
    endpoint still must show a chronologically consistent funnel: the implied
    open and click happen at the moment the form was displayed, and the counters
    agree with the timestamps.
    """
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    uid = str(tracking.tracking_uuid)

    await service.mark_form_viewed(uid, db, "1.2.3.4", "UA/1")
    await db.commit()
    await db.refresh(tracking)
    viewed_at = tracking.form_viewed_at
    assert viewed_at is not None

    await service.log_submission(
        uid,
        "employee@acmetest.example",
        "Secret123",
        9,
        {"password": "Secret123"},
        "1.2.3.4",
        "UA/1",
        db,
    )
    await db.commit()
    await db.refresh(tracking)

    assert tracking.opened_at == viewed_at
    assert tracking.clicked_at == viewed_at
    assert tracking.open_count == 1
    assert tracking.click_count == 1
    assert tracking.opened_at <= tracking.form_viewed_at
    assert tracking.clicked_at <= tracking.form_submitted_at


async def test_interaction_ledger_records_every_state_change(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """Open, click, view, submit, report and completion each append a row."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    uid = str(tracking.tracking_uuid)

    await service.log_open(uid, "1.2.3.4", "UA/1", db)
    await service.log_click(uid, "1.2.3.4", "UA/1", db)
    await service.mark_form_viewed(uid, db, "1.2.3.4", "UA/1")
    await service.log_submission(
        uid,
        "employee@acmetest.example",
        "Secret123",
        None,
        {"password": "Secret123"},
        "1.2.3.4",
        "UA/1",
        db,
        client={"seconds_on_form": 12},
    )
    await service.log_simulation_report(uid, "1.2.3.4", "UA/1", db)
    await service.log_completion(uid, db)
    await db.commit()

    from sqlalchemy import select

    rows = (
        (
            await db.execute(
                select(TrainingInteraction)
                .where(TrainingInteraction.tracking_id == tracking.id)
                .order_by(TrainingInteraction.occurred_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [row.event_type for row in rows] == [
        "email_open",
        "link_click",
        "form_viewed",
        "form_submitted",
        "phishing_reported",
        "training_completed",
    ]
    # Every event carries an exact timestamp and the campaign/employee keys.
    for row in rows:
        assert row.occurred_at is not None
        assert row.campaign_id == tracking.campaign_id
        assert row.employee_id == tracking.employee_id
    submission = next(row for row in rows if row.event_type == "form_submitted")
    assert decrypt_payload(submission.payload_encrypted) == {
        "identifier": "employee@acmetest.example",
        "password": "Secret123",
    }
    assert submission.details["client"] == {"seconds_on_form": 12}


async def test_repeated_opens_and_submissions_are_preserved(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The ledger keeps repeats instead of collapsing them into a counter."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    uid = str(tracking.tracking_uuid)

    await service.log_open(uid, "1.2.3.4", "UA", db)
    await service.log_open(uid, "1.2.3.4", "UA", db)
    await service.log_submission(uid, "a@b.c", "one", None, {}, None, None, db)
    await service.log_submission(uid, "a@b.c", "two", None, {}, None, None, db)
    await db.commit()
    await db.refresh(tracking)

    from sqlalchemy import func, select

    opens = await db.scalar(
        select(func.count(TrainingInteraction.id)).where(
            TrainingInteraction.tracking_id == tracking.id,
            TrainingInteraction.event_type == "email_open",
        )
    )
    assert opens == 2
    assert tracking.submission_count == 2
    # Only the first submission moves the employee counter.
    assert employee.total_credential_submissions == 1
    # The latest payload is what the tracking row exposes.
    assert decrypt_payload(tracking.submitted_payload_encrypted)["password"] == "two"


def test_encrypt_payload_round_trip_and_invalid_token() -> None:
    """Encryption is lossless and corrupt tokens degrade to an empty mapping."""
    assert encrypt_payload(None) is None
    assert encrypt_payload({}) is None
    token = encrypt_payload({"password": "p@ss", "office": "Cairo"})
    assert token is not None and token.startswith("enc:v1:")
    assert decrypt_payload(token) == {"password": "p@ss", "office": "Cairo"}
    assert decrypt_payload(None) == {}
    assert decrypt_payload("enc:v1:not-real") == {}


def test_normalize_submitted_values_orders_and_deduplicates() -> None:
    """Identifier and password come first and fields never overwrite them."""
    values = normalize_submitted_values(
        "a@b.c", "hunter2", {"password": "ignored", "identifier": "ignored", "office": "Cairo"}
    )
    assert list(values) == ["identifier", "password", "office"]
    assert values["identifier"] == "a@b.c"
    assert values["password"] == "hunter2"
    assert values["office"] == "Cairo"
    assert normalize_submitted_values(None, None, None) == {}
    # Hostile values are truncated and non-mappings ignored.
    long_value = normalize_submitted_values(None, None, {"x": "y" * 5000})
    assert len(long_value["x"]) == 512
    assert normalize_submitted_values(None, None, ["not", "a", "mapping"]) == {}


def test_sanitize_submitted_fields_drops_secrets() -> None:
    """The plain snapshot never contains secret-looking keys."""
    clean = sanitize_submitted_fields(
        {"password": "x", "user_password": "x", "api-token": "x", "office": "Cairo"}
    )
    assert clean == {"office": "Cairo"}
    assert sanitize_submitted_fields(None) == {}
    assert sanitize_submitted_fields("nope") == {}


# --------------------------------------------------------------------------- #
# Elo adaptive difficulty
# --------------------------------------------------------------------------- #
async def test_elo_click_penalty_applies_once(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """The first click costs the email/easy channel delta; repeats are free."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    for _ in range(3):
        await service.log_click(str(tracking.tracking_uuid), "198.51.100.9", "UA", db)
        await db.commit()

    await db.refresh(employee)
    assert employee.elo_score == 955


async def test_elo_report_reward_applies_once(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """A click (-45) plus one report (+75) uses the smart channel weights."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()

    await service.log_click(str(tracking.tracking_uuid), "198.51.100.9", "UA", db)
    await db.commit()
    await service.log_simulation_report(
        str(tracking.tracking_uuid), "198.51.100.9", "UA", db
    )
    await db.commit()
    # The second report is a no-op and must not grant another reward.
    await service.log_simulation_report(
        str(tracking.tracking_uuid), "198.51.100.9", "UA", db
    )
    await db.commit()

    await db.refresh(employee)
    assert employee.elo_score == 1030


async def test_elo_direct_submission_backfills_click_once(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """A direct form submission is one submission-level failure, not click+submit."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    await service.mark_form_viewed(
        str(tracking.tracking_uuid), db, "198.51.100.9", "UA"
    )
    await db.commit()

    await service.log_submission(
        str(tracking.tracking_uuid),
        "jane@acmetest.example",
        "secret",
        6,
        {"office": "Cairo"},
        "198.51.100.9",
        "UA",
        db,
    )
    await db.commit()
    await service.log_submission(
        str(tracking.tracking_uuid),
        "jane@acmetest.example",
        "secret2",
        7,
        {"office": "Cairo"},
        "198.51.100.9",
        "UA",
        db,
    )
    await db.commit()

    await db.refresh(employee)
    assert employee.elo_score == 910


async def test_elo_admin_report_safe_does_not_double_reward(
    db: AsyncSession, organization, employee, builtin_templates
) -> None:
    """An admin report-safe after the public report does not add another reward."""
    tracking = await _make_tracking(db, organization, employee, builtin_templates[0])
    service = TrackingService()
    await service.log_simulation_report(
        str(tracking.tracking_uuid), "198.51.100.9", "UA", db
    )
    await db.commit()
    await db.refresh(employee)
    assert employee.elo_score == 1075

    result = await service.mark_reported_safe(
        str(tracking.tracking_uuid), db, actor="tester"
    )
    await db.commit()
    assert result is not None
    await db.refresh(employee)
    assert employee.elo_score == 1075
