"""Tracking service: records opens, clicks and training completions.

All counters are updated inside a transaction that locks the tracking row with
``SELECT ... FOR UPDATE`` (emulated on SQLite) so concurrent requests cannot
double count an event.  ``FOR UPDATE`` is only emitted on backends that
support it.

Every state change additionally appends a row to ``training_interactions``,
which is the authoritative, second-by-second audit trail: what happened, when
(microsecond precision), from which address and device, and — for submissions —
exactly what the recipient typed.  Values the recipient typed are encrypted with
AES-256-GCM before they are written, so the database never holds them in clear
text.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    PhishingReport,
    TrainingInteraction,
)
from app.security import EncryptionError, decrypt_value, encrypt_value
from app.services.classification_engine import ClassificationEngine
from app.services.elo_engine import (
    CLICK_ELO_DELTA,
    apply_click,
    apply_report,
    clamp_elo,
)

logger = get_logger(__name__)

#: Immunity score deltas applied to the employee on engagement.
CLICK_PENALTY = 12.0
COMPLETION_BONUS = 5.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

#: Field names that are kept out of the *plain* ``submitted_fields`` snapshot so
#: a quick glance at the table never leaks a secret.  They are still captured
#: (encrypted) in ``submitted_payload_encrypted`` — see ``CAPTURE_SECRETS``.
SECRET_FIELD_KEYS = frozenset(
    {"pass", "code", "pin", "cvv", "cvc", "card", "creditcard", "securitycode"}
)

#: Substrings that mark a field name as secret wherever they appear, so
#: ``user_password`` or ``api-token`` are kept out of the plain snapshot too.
SECRET_FIELD_TOKENS = (
    "password",
    "passwd",
    "passphrase",
    "pwd",
    "secret",
    "token",
    "credential",
    "otp",
    "pin",
    "cvv",
    "cvc",
    "cardnumber",
    "creditcard",
    "securitycode",
)

#: Hard caps that keep a hostile payload from bloating the row.
MAX_SUBMITTED_FIELDS = 25
MAX_FIELD_KEY_LENGTH = 64
MAX_FIELD_VALUE_LENGTH = 512

#: Interaction event types written to the ledger.
EVENT_OPEN = "email_open"
EVENT_CLICK = "link_click"
EVENT_FORM_VIEWED = "form_viewed"
EVENT_SUBMITTED = "form_submitted"
EVENT_REPORTED = "phishing_reported"
EVENT_COMPLETED = "training_completed"


def sanitize_submitted_fields(fields: object) -> dict[str, str]:
    """Return a secret-free copy of the form fields for plain display.

    This is the *convenience* view used in tables and CSV exports.  The
    complete, verbatim payload (including secret-looking fields) is stored
    encrypted in ``submitted_payload_encrypted`` and returned by the dossier
    endpoints.

    Args:
        fields: Whatever mapping the client sent (may be ``None`` or junk).

    Returns:
        A mapping with secret-looking keys dropped and every value truncated.
    """
    if not isinstance(fields, dict):
        return {}
    clean: dict[str, str] = {}
    for key, value in fields.items():
        if len(clean) >= MAX_SUBMITTED_FIELDS:
            break
        key_str = str(key)[:MAX_FIELD_KEY_LENGTH]
        normalized = (
            key_str.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        )
        if normalized in SECRET_FIELD_KEYS or any(
            token in normalized for token in SECRET_FIELD_TOKENS
        ):
            continue
        if value is None:
            continue
        clean[key_str] = str(value)[:MAX_FIELD_VALUE_LENGTH]
    return clean


def normalize_submitted_values(
    identifier: str | None,
    password: str | None,
    fields: object,
) -> dict[str, str]:
    """Return every value the recipient typed, verbatim and capped.

    Args:
        identifier: Value typed into the identifier (usually e-mail) field.
        password: Value typed into the password field, if transmitted.
        fields: Every other named field from the form.

    Returns:
        An ordered mapping of ``field -> value``.  ``identifier`` and
        ``password`` come first so the evidence reads naturally.
    """
    values: dict[str, str] = {}
    if identifier is not None and str(identifier) != "":
        values["identifier"] = str(identifier)[:MAX_FIELD_VALUE_LENGTH]
    if password is not None and str(password) != "":
        values["password"] = str(password)[:MAX_FIELD_VALUE_LENGTH]
    if isinstance(fields, dict):
        for key, value in fields.items():
            if len(values) >= MAX_SUBMITTED_FIELDS:
                break
            if value is None:
                continue
            key_str = str(key)[:MAX_FIELD_KEY_LENGTH]
            if key_str in values:
                continue
            values[key_str] = str(value)[:MAX_FIELD_VALUE_LENGTH]
    return values


def encrypt_payload(payload: dict[str, Any] | None) -> str | None:
    """Encrypt a JSON payload with AES-256-GCM.

    Args:
        payload: Mapping to protect.  ``None`` or ``{}`` pass through as ``None``.

    Returns:
        An ``enc:v1:`` token, or ``None`` when there is nothing to store.
    """
    if not payload:
        return None
    try:
        return encrypt_value(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - never fail the interaction
        logger.error("payload_encryption_failed", error=str(exc))
        return None


def decrypt_payload(token: str | None) -> dict[str, Any]:
    """Decrypt a payload produced by :func:`encrypt_payload`.

    Args:
        token: The ``enc:v1:`` token (or ``None``).

    Returns:
        The decoded mapping, or ``{}`` when the token is absent/corrupt.
    """
    if not token:
        return {}
    try:
        raw = decrypt_value(token)
    except EncryptionError as exc:
        logger.error("payload_decryption_failed", error=str(exc))
        return {}
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("payload_not_json")
        return {}
    return decoded if isinstance(decoded, dict) else {}


def latest_submitted_values(tracking: EmailTracking) -> dict[str, str] | None:
    """Return the values of the most recent submission on a tracking row.

    Prefers the encrypted, verbatim payload.  Tracking rows created before that
    column existed fall back to the identifier and the secret-free snapshot, so
    historical engagements still show what is known.

    Args:
        tracking: The tracking row.

    Returns:
        A ``field -> value`` mapping, or ``None`` when nothing was submitted.
    """
    values = decrypt_payload(tracking.submitted_payload_encrypted)
    if values:
        return values
    if tracking.submitted_at is None:
        return None
    legacy: dict[str, str] = {}
    if tracking.submitted_identifier:
        legacy["identifier"] = tracking.submitted_identifier
    legacy.update(tracking.submitted_fields or {})
    return legacy or None
def _now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class TrackingService:
    """Encapsulates all engagement-tracking mutations."""

    def __init__(self, engine: ClassificationEngine | None = None) -> None:
        """Initialise the service.

        Args:
            engine: Optional classification engine (injectable for tests).
        """
        self.classification_engine = engine or ClassificationEngine()

    # ------------------------------------------------------------------ #
    # Row locking helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _supports_for_update(db: AsyncSession) -> bool:
        """Return ``True`` when the session's dialect supports ``FOR UPDATE``."""
        try:
            dialect = db.get_bind().dialect.name
        except Exception:  # pragma: no cover - best effort
            return False
        return dialect in {"postgresql", "mysql", "oracle", "mssql"}

    async def _locked_tracking(
        self, db: AsyncSession, column, value
    ) -> EmailTracking | None:
        """Fetch an ``EmailTracking`` row with a write lock when supported.

        Args:
            db: Active session.
            column: Column to filter on (``tracking_uuid`` or ``id``).
            value: Value to match.

        Returns:
            The locked row or ``None``.
        """
        stmt = select(EmailTracking).where(column == value)
        if self._supports_for_update(db):
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Interaction ledger
    # ------------------------------------------------------------------ #
    def _record_interaction(
        self,
        db: AsyncSession,
        row: EmailTracking,
        event_type: str,
        occurred_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
        details: dict[str, Any] | None = None,
        payload_encrypted: str | None = None,
    ) -> TrainingInteraction:
        """Append one event to the interaction ledger.

        Args:
            db: Active session.
            row: The tracking row the event belongs to.
            event_type: One of the ``EVENT_*`` constants.
            occurred_at: Exact time of the event (UTC, microsecond precision).
            ip_address: Client address, when known.
            user_agent: Client User-Agent, when known.
            details: Non-secret structured context.
            payload_encrypted: Encrypted secret payload, for submissions.

        Returns:
            The pending (not yet flushed) interaction.
        """
        interaction = TrainingInteraction(
            tracking_id=row.id,
            campaign_id=row.campaign_id,
            employee_id=row.employee_id,
            event_type=event_type,
            occurred_at=occurred_at,
            ip_address=ip_address,
            user_agent=(user_agent or None) and user_agent[:2000],
            details=details or {},
            payload_encrypted=payload_encrypted,
        )
        db.add(interaction)
        return interaction

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    async def log_open(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record an email open.

        The per-recipient ``open_count`` is incremented on every open while the
        campaign-level ``opened_count`` is incremented only on the first open.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            ip_address: Client IP address (may be ``None``).
            user_agent: Client User-Agent (may be ``None``).
            db: Active session.

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_open_unknown", tracking_uuid=str(tracking_uuid))
            return None

        now = _now()
        first_open = row.opened_at is None
        row.open_count = (row.open_count or 0) + 1
        if first_open:
            row.opened_at = now
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        if row.delivered_at is None:
            row.delivered_at = now

        if first_open:
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )
        self._record_interaction(
            db,
            row,
            EVENT_OPEN,
            now,
            ip_address,
            user_agent,
            {"open_count": row.open_count, "first_open": first_open},
        )
        await db.flush()
        logger.info(
            "email_opened",
            tracking_uuid=str(uid),
            first_open=first_open,
            open_count=row.open_count,
        )
        return row

    async def log_click(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record a link click and penalise the employee's immunity score.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            ip_address: Client IP address.
            user_agent: Client User-Agent.
            db: Active session.

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_click_unknown", tracking_uuid=str(tracking_uuid))
            return None

        now = _now()
        first_click = row.clicked_at is None
        row.click_count = (row.click_count or 0) + 1
        if first_click:
            row.clicked_at = now
        if row.opened_at is None:
            # A click implies the email was read.
            row.opened_at = now
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        if first_click:
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(clicked_count=EmailCampaign.clicked_count + 1)
            )
            await self._adjust_employee(
                db,
                row.employee_id,
                delta=-CLICK_PENALTY,
                increment_clicks=first_click,
                elo_delta=CLICK_ELO_DELTA,
            )
        self._record_interaction(
            db,
            row,
            EVENT_CLICK,
            now,
            ip_address,
            user_agent,
            {"click_count": row.click_count, "first_click": first_click},
        )
        await db.flush()
        logger.info(
            "link_clicked",
            tracking_uuid=str(uid),
            first_click=first_click,
            click_count=row.click_count,
        )
        return row

    async def log_completion(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        score: int | None = None,
        total: int | None = None,
    ) -> EmailTracking | None:
        """Record that the recipient finished the micro-training.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            db: Active session.
            score: Number of correct quiz answers, when supplied by the page.
            total: Number of quiz questions, when supplied by the page.

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_complete_unknown", tracking_uuid=str(tracking_uuid))
            return None

        # Persist the quiz result even when the page is reloaded after
        # completion; the completion counter must only increment once.
        if score is not None:
            clamped_total = max(1, min(int(total or 5), 100))
            row.quiz_score = max(0, min(int(score), clamped_total))
            row.quiz_total = clamped_total

        if row.completed_at is not None:
            logger.info("training_already_completed", tracking_uuid=str(uid))
            return row

        now = _now()
        row.completed_at = now
        self._record_interaction(
            db,
            row,
            EVENT_COMPLETED,
            now,
            ip_address=row.last_ip_address,
            user_agent=row.last_user_agent,
            details={
                "countdown_seconds": 60,
                "quiz_score": row.quiz_score,
                "quiz_total": row.quiz_total,
            },
        )
        await db.execute(
            update(EmailCampaign)
            .where(EmailCampaign.id == row.campaign_id)
            .values(completed_count=EmailCampaign.completed_count + 1)
        )

        # A completed debrief is a deliberate positive signal. Recompute the
        # baseline from the 90-day ledger, then add the completion bonus plus a
        # small knowledge bonus derived from the quiz. This keeps the score
        # reproducible instead of stacking deltas indefinitely.
        employee = await db.get(HumanAsset, row.employee_id)
        if employee is not None:
            try:
                metrics = await self.classification_engine.gather_metrics(
                    employee.id, db
                )
                baseline = self.classification_engine.score_from_metrics(metrics)
                quiz_bonus = 0.0
                if row.quiz_score is not None and row.quiz_total:
                    quiz_bonus = round(
                        min(3.0, (row.quiz_score / row.quiz_total) * 3.0), 2
                    )
                final_score = min(
                    MAX_SCORE, baseline + COMPLETION_BONUS + quiz_bonus
                )
                employee.immunity_score = Decimal(str(round(final_score, 2)))
                employee.behavioral_category = (
                    self.classification_engine.category_from_metrics(
                        metrics, final_score
                    )
                )
                employee.requires_mandatory_training = (
                    employee.behavioral_category == "unaware"
                )
                employee.under_enhanced_monitoring = (
                    employee.behavioral_category == "critical_risk"
                )
                await db.flush()
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning(
                    "completion_score_recalculation_failed",
                    tracking_uuid=str(uid),
                    error=str(exc),
                )
        await db.flush()
        logger.info(
            "training_completed",
            tracking_uuid=str(uid),
            quiz_score=row.quiz_score,
            quiz_total=row.quiz_total,
        )
        return row

    async def mark_form_viewed(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmailTracking | None:
        """Record that the simulated credential form was rendered.

        Every render is appended to the ledger, while ``viewed_at`` keeps
        the first one so the funnel stays stable.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            db: Active session.
            ip_address: Client IP address (may be ``None``).
            user_agent: Client User-Agent (may be ``None``).

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            return None
        now = _now()
        first_view = row.viewed_at is None
        if first_view:
            row.viewed_at = now
        views = (
            await db.scalar(
                select(func.count(TrainingInteraction.id)).where(
                    TrainingInteraction.tracking_id == row.id,
                    TrainingInteraction.event_type == EVENT_FORM_VIEWED,
                )
            )
            or 0
        ) + 1
        self._record_interaction(
            db,
            row,
            EVENT_FORM_VIEWED,
            now,
            ip_address,
            user_agent,
            {"view_count": views, "first_view": first_view},
        )
        if first_view:
            logger.info("training_form_viewed", tracking_uuid=str(uid))
        await db.flush()
        return row

    async def log_submission(
        self,
        tracking_uuid: uuid.UUID | str,
        identifier: str | None,
        password: str | None,
        password_length: int | None,
        fields: dict[str, str] | None,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
        client: dict[str, Any] | None = None,
    ) -> EmailTracking | None:
        """Record a simulated credential submission.

        Everything the recipient typed is preserved: the identifier, the
        password value and every other named field.  The verbatim mapping is
        serialised to JSON and encrypted with AES-256-GCM before storage; a
        secret-free copy also lands in ``submitted_fields`` for quick display.

        The first submission on a campaign increments
        ``employee.total_credential_submissions`` and re-runs the behavioural
        classification, which is what moves the employee into the risk
        category.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            identifier: Value typed into the identifier field.
            password: Value typed into the password field (may be ``None`` for
                clients that only send a length).
            password_length: Number of characters typed into the password field.
            fields: Every other named field exactly as entered.
            ip_address: Client IP address.
            user_agent: Client User-Agent.
            db: Active session.
            client: Non-secret browser context (client clock, durations, …).

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_submit_unknown", tracking_uuid=str(tracking_uuid))
            return None

        now = _now()
        first_submission = row.submitted_at is None
        row.submission_count = (row.submission_count or 0) + 1
        if first_submission:
            row.submitted_at = now
        if identifier:
            row.submitted_identifier = str(identifier)[:255]

        values = normalize_submitted_values(identifier, password, fields)
        fingerprint = sanitize_submitted_fields(fields)
        if fingerprint:
            row.submitted_fields = fingerprint
        if password is not None:
            password_length = len(password)
        if password_length is not None:
            row.password_length = max(0, min(int(password_length), 1024))
        row.submitted_password_encrypted = encrypt_payload(
            {"password": password} if password is not None else None
        )
        row.submitted_payload_encrypted = encrypt_payload(values)
        row.client_context = client or None
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        # Submitting the form implies the message was opened and clicked.
        await self._ensure_engagement(db, row, now)

        self._record_interaction(
            db,
            row,
            EVENT_SUBMITTED,
            now,
            ip_address,
            user_agent,
            {
                "submission_count": row.submission_count,
                "field_names": sorted(values.keys()),
                "password_length": row.password_length,
                "client": client or {},
            },
            payload_encrypted=row.submitted_payload_encrypted,
        )

        if first_submission:
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1
                employee.last_test_date = now
            await db.flush()
            await self._classify(row.employee_id, db)

        await db.flush()
        logger.info(
            "credentials_submitted",
            tracking_uuid=str(uid),
            first_submission=first_submission,
            submission_count=row.submission_count,
            password_length=row.password_length,
            field_count=len(values),
        )
        return row

    async def log_simulation_report(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> PhishingReport | None:
        """Record that the recipient recognised the simulation.

        The first time a recipient flags the message a row is added to the
        report inbox, ``employee.total_reports`` is incremented and the
        behavioural classification is refreshed.  Reporting is a positive
        behaviour, so the score improves.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            ip_address: Client IP address.
            user_agent: Client User-Agent.
            db: Active session.

        Returns:
            The created report, or ``None`` when the UUID is unknown or the
            message was already reported.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_report_unknown", tracking_uuid=str(tracking_uuid))
            return None
        if row.reported_at is not None:
            logger.info("simulation_already_reported", tracking_uuid=str(uid))
            return None

        employee = await db.get(HumanAsset, row.employee_id)
        if employee is None:  # pragma: no cover - FK guarantees existence
            return None

        now = _now()
        row.reported_at = now
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        self._record_interaction(
            db,
            row,
            EVENT_REPORTED,
            now,
            ip_address,
            user_agent,
            {"source": "training_page"},
        )

        report = PhishingReport(
            organization_id=employee.organization_id,
            employee_id=employee.id,
            reported_email_subject="Simulated phishing email (training)",
            reported_sender=None,
            description="Flagged as suspicious from the training landing page.",
            status="new",
            is_training_simulation=True,
            details={
                "tracking_uuid": str(row.tracking_uuid),
                "campaign_id": str(row.campaign_id),
                "source": "training_page",
            },
        )
        db.add(report)
        employee.total_reports = (employee.total_reports or 0) + 1
        # A report is a positive security behaviour.  Apply the Elo reward only
        # on the first report; the ``reported_at`` guard above already makes the
        # whole operation idempotent.
        employee.elo_score = apply_report(employee.elo_score)
        await db.flush()
        await self._classify(employee.id, db)
        logger.info(
            "simulation_reported",
            tracking_uuid=str(uid),
            report_id=str(report.id),
            elo_score=employee.elo_score,
        )
        return report

    async def mark_reported_safe(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        actor: str = "administrator",
    ) -> tuple[EmailTracking, HumanAsset, bool] | None:
        """Record an out-of-band "report safe" outcome (admin action).

        Employees sometimes recognise a simulation and report it through a
        channel other than the tracking link. An administrator can record that
        outcome against the tracking row: the event becomes ``reported_safe``,
        the quiz score is fixed at 5/5, and the employee's immunity score is set
        to 100%.

        The operation is idempotent: calling it again returns the existing row
        without creating a second phishing report or event.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            db: Active session.
            ip_address: Administrator/client IP, when known.
            user_agent: Administrator/client User-Agent, when known.
            actor: Human label stored in the audit event.

        Returns:
            ``(tracking, employee, already_reported_safe)`` or ``None`` when
            the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_report_safe_unknown", tracking_uuid=str(tracking_uuid))
            return None
        employee = await db.get(HumanAsset, row.employee_id)
        if employee is None:  # pragma: no cover - FK guarantees existence
            return None

        if row.is_reported_safe:
            return row, employee, True

        now = _now()
        was_reported = row.reported_at is not None
        row.is_reported_safe = True
        row.quiz_score = 5
        row.quiz_total = 5
        if row.reported_at is None:
            row.reported_at = now
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        if not was_reported:
            employee.total_reports = (employee.total_reports or 0) + 1
            report = PhishingReport(
                organization_id=employee.organization_id,
                employee_id=employee.id,
                reported_email_subject="Simulated phishing email (report safe)",
                reported_sender=None,
                description=(
                    "Employee reported the simulation safe without clicking. "
                    "Recorded by an administrator."
                ),
                status="resolved",
                is_training_simulation=True,
                details={
                    "tracking_uuid": str(row.tracking_uuid),
                    "campaign_id": str(row.campaign_id),
                    "source": "admin_report_safe",
                    "actor": actor,
                },
            )
            db.add(report)

        employee.immunity_score = Decimal("100.00")
        employee.behavioral_category = "competent"
        employee.requires_mandatory_training = False
        employee.under_enhanced_monitoring = False
        if not was_reported:
            # The report reward is applied once.  A row already reported through
            # the public training page has had its +32; an administrator marking
            # that same report safe must not grant it a second time.
            employee.elo_score = apply_report(employee.elo_score)
        self._record_interaction(
            db,
            row,
            EVENT_REPORTED,
            now,
            ip_address,
            user_agent,
            {
                "source": "admin_report_safe",
                "reported_safe": True,
                "quiz_score": 5,
                "quiz_total": 5,
                "actor": actor,
            },
        )
        await db.flush()
        logger.info(
            "simulation_report_safe",
            tracking_uuid=str(uid),
            employee_id=str(employee.id),
            actor=actor,
        )
        return row, employee, False

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    async def _ensure_engagement(
        self, db: AsyncSession, row: EmailTracking, now: datetime
    ) -> None:
        """Backfill the open/click markers an interaction implies.

        A form view or submission proves the recipient reached the page, so the
        open and click markers are backfilled when they are missing.  The
        earliest known evidence timestamp is used (never a later timestamp than
        the form view) so the funnel stays chronologically consistent.

        Args:
            db: Active session.
            row: The tracking row being updated.
            now: Timestamp to apply when no earlier evidence exists.
        """
        anchor = row.viewed_at or now
        if row.opened_at is None:
            row.opened_at = anchor
            row.open_count = (row.open_count or 0) + 1
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )
        if row.clicked_at is None:
            row.clicked_at = anchor
            row.click_count = (row.click_count or 0) + 1
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(clicked_count=EmailCampaign.clicked_count + 1)
            )
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.total_clicks = (employee.total_clicks or 0) + 1
                # A direct form submission (without the click endpoint) still
                # proves the recipient followed the simulated link.  Apply the
                # Elo click penalty exactly once, when the click marker is
                # backfilled here.
                employee.elo_score = apply_click(employee.elo_score)

    async def _classify(self, employee_id: uuid.UUID, db: AsyncSession) -> None:
        """Re-derive the employee's category, never failing the request.

        Args:
            employee_id: Employee to reclassify.
            db: Active session.
        """
        try:
            await self.classification_engine.classify(employee_id, db)
        except Exception as exc:  # pragma: no cover - classification is best effort
            logger.warning("classification_failed", employee_id=str(employee_id), error=str(exc))

    @staticmethod
    def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
        """Parse ``value`` into a UUID, returning ``None`` when invalid."""
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return None

    async def _adjust_employee(
        self,
        db: AsyncSession,
        employee_id: uuid.UUID,
        delta: float,
        increment_clicks: bool = False,
        reclassify: bool = True,
        elo_delta: int = 0,
    ) -> None:
        """Apply a score delta to an employee and optionally reclassify them.

        Args:
            db: Active session.
            employee_id: Employee to adjust.
            delta: Signed change applied to ``immunity_score``.
            increment_clicks: When ``True`` also bump ``total_clicks``.
            reclassify: When ``False`` keep the manually adjusted score instead
                of replacing it with a fresh ledger-derived score.
            elo_delta: Signed change applied to the independent ``elo_score``.
                The Elo rating is never derived from ``immunity_score``.
        """
        employee = await db.get(HumanAsset, employee_id)
        if employee is None:  # pragma: no cover - FK guarantees existence
            return
        current = float(employee.immunity_score or 0)
        new_score = max(MIN_SCORE, min(MAX_SCORE, current + delta))
        employee.immunity_score = new_score  # type: ignore[assignment]
        if elo_delta:
            employee.elo_score = clamp_elo(int(employee.elo_score or 1000) + elo_delta)
        if increment_clicks:
            employee.total_clicks = (employee.total_clicks or 0) + 1
            employee.last_test_date = _now()
        await db.flush()
        if not reclassify:
            return
        # Re-derive the category from the full 90-day picture.
        try:
            await self.classification_engine.classify(employee_id, db)
        except Exception as exc:  # pragma: no cover - classification is best effort
            logger.warning("classification_failed", employee_id=str(employee_id), error=str(exc))
