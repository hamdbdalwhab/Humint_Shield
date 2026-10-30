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
import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models import (
    EmailCampaign,
    EmailTracking,
    HumanAsset,
    PhishingReport,
    QRScan,
    TrainingInteraction,
)
from app.security import EncryptionError, decrypt_value, encrypt_value
from app.services.classification_engine import ClassificationEngine
from app.services.elo_engine import (
    CLICK_ELO_DELTA,
    OTP_SUBMISSION_ELO_DELTA,
    PRETEXTING_FRAUD_ELO_DELTA,
    PRETEXTING_REPORT_ELO_DELTA,
    QR_CREDENTIAL_ELO_DELTA,
    QR_SCAN_ELO_DELTA,
    USB_OPEN_ELO_DELTA,
    VISHING_CREDENTIAL_ELO_DELTA,
    VISHING_REPORT_ELO_DELTA,
    apply_click,
    apply_elo_delta,
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
EVENT_OTP_SUBMITTED = "otp_submitted"
EVENT_REPORTED = "phishing_reported"
EVENT_COMPLETED = "training_completed"
EVENT_QR_SCANNED = "qr_scanned"
EVENT_CREDENTIAL_SUBMITTED = "credential_submitted"
EVENT_USB_OPENED = "usb_opened"
EVENT_CREDENTIAL_DISCLOSED = "credential_disclosed"
EVENT_FINANCIAL_FRAUD = "financial_fraud"
EVENT_REPORTED_PHISH = "reported_phish"
EVENT_QR_IDENTITY_ASSIGNED = "qr_identity_assigned"

#: Identity resolution outcomes stored on tracking rows and QR scans.
IDENTITY_MATCHED_EMAIL = "matched_email"
IDENTITY_MATCHED_USERNAME = "matched_username"
IDENTITY_UNKNOWN = "unknown"
IDENTITY_MANUAL = "manual"


@dataclass(slots=True)
class QRSubmissionResult:
    """Result of one QR/quishing credential submission.

    ``tracking`` is ``None`` for a campaign-level scan whose entered identity
    could not be linked to an existing recipient row.  ``scan`` is always the
    :class:`QRScan` ledger row used by the admin Live scans table.
    """

    scan: QRScan
    tracking: EmailTracking | None
    employee: HumanAsset | None
    identity_resolution: str
    elo_delta: int
    first_time: bool


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
        capture_secret: bool = True,
    ) -> EmailTracking | None:
        """Record a simulated credential submission.

        QR/quishing rows are deliberately **secret-free**: the channel forces
        ``capture_secret`` off, discards any password value before it reaches
        the database, and keeps only the identifier, password length and
        non-secret field names.  A first QR submission also applies the
        quishing failure penalty exactly once and records the distinct
        ``credential_submitted`` event.  The QR page is reached from a printed
        poster, not an email, so it must not inherit the email click penalty.

        Other channels preserve the historical behaviour: when
        ``capture_secret`` is true the verbatim payload is encrypted with
        AES-256-GCM; when false the password is discarded.  The first
        submission increments ``employee.total_credential_submissions`` and
        re-runs the behavioural classification.

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
            capture_secret: Whether a non-QR channel may encrypt the password.

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

        channel = (row.channel or "email").strip().lower()
        is_qr = channel == "qr"
        if is_qr:
            # A quishing page must never persist the typed password, even if a
            # caller forgets to set capture_secret=false.
            capture_secret = False

        now = _now()
        first_submission = row.submitted_at is None
        row.submission_count = (row.submission_count or 0) + 1
        if first_submission:
            row.submitted_at = now
        if identifier:
            row.submitted_identifier = str(identifier)[:255]

        if password is not None:
            password_length = len(password)
        if not capture_secret:
            # Never persist the actual secret.  Keep only non-secret field
            # metadata and the password length for the behavioural report.
            password = None
            fields = sanitize_submitted_fields(fields)
        values = normalize_submitted_values(identifier, password, fields)
        fingerprint = sanitize_submitted_fields(fields)
        if fingerprint:
            row.submitted_fields = fingerprint
        if password_length is not None:
            row.password_length = max(0, min(int(password_length), 1024))
        row.submitted_password_encrypted = (
            encrypt_payload({"password": password})
            if capture_secret and password is not None
            else None
        )
        row.submitted_payload_encrypted = encrypt_payload(values)
        row.client_context = client or None
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        # Submitting the form implies the message was opened and clicked.  QR
        # rows use the score-neutral visit helper: their -25 failure penalty is
        # applied below, once, instead of the email channel's -32 click.
        if is_qr:
            await self._ensure_visit(db, row, now)
        else:
            await self._ensure_engagement(db, row, now)

        elo_delta = 0
        if first_submission:
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1
                employee.last_test_date = now
                if is_qr:
                    employee.elo_score = apply_elo_delta(
                        employee.elo_score, QR_CREDENTIAL_ELO_DELTA
                    )
                    elo_delta = QR_CREDENTIAL_ELO_DELTA
            await db.flush()

        self._record_interaction(
            db,
            row,
            EVENT_CREDENTIAL_SUBMITTED if is_qr else EVENT_SUBMITTED,
            now,
            ip_address,
            user_agent,
            {
                "channel": channel,
                "submission_count": row.submission_count,
                "field_names": sorted(values.keys()),
                "password_length": row.password_length,
                "password_stored": bool(capture_secret and row.submitted_password_encrypted),
                "elo_delta": elo_delta,
                "client": client or {},
            },
            payload_encrypted=row.submitted_payload_encrypted,
        )

        if first_submission:
            await self._classify(row.employee_id, db)

        await db.flush()
        logger.info(
            "credentials_submitted",
            tracking_uuid=str(uid),
            channel=channel,
            first_submission=first_submission,
            submission_count=row.submission_count,
            password_length=row.password_length,
            field_count=len(values),
            elo_delta=elo_delta,
        )
        return row

    async def log_otp_submission(
        self,
        tracking_uuid: uuid.UUID | str,
        otp_code: str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record an MFA (OTP) bypass submission and apply the -15 Elo penalty.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            otp_code: Verification code typed by the recipient.
            ip_address: Client IP address.
            user_agent: Client User-Agent.
            db: Active database session.

        Returns:
            The updated tracking row, or None when unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_otp_unknown", tracking_uuid=str(tracking_uuid))
            return None

        now = _now()
        first_otp = not row.otp_submitted
        row.otp_submitted = True
        row.otp_submitted_at = now
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        elo_delta = 0
        if first_otp:
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, OTP_SUBMISSION_ELO_DELTA
                )
                elo_delta = OTP_SUBMISSION_ELO_DELTA
            await db.flush()

        self._record_interaction(
            db,
            row,
            EVENT_OTP_SUBMITTED,
            now,
            ip_address,
            user_agent,
            {
                "channel": row.channel or "email",
                "otp_length": len(otp_code),
                "first_otp": first_otp,
                "elo_delta": elo_delta,
            },
        )
        if first_otp:
            await self._classify(row.employee_id, db)

        await db.flush()
        logger.info(
            "otp_submitted",
            tracking_uuid=str(uid),
            first_otp=first_otp,
            elo_delta=elo_delta,
        )
        return row

    @staticmethod
    def generate_short_code(length: int = 6) -> str:
        """Generate a random alphanumeric short code."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def get_or_create_short_code(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
    ) -> str | None:
        """Get or generate an indexed unique short URL code for tracking.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            db: Active database session.

        Returns:
            The alphanumeric short code, or None if tracking row doesn't exist.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            return None
        if row.short_code:
            return row.short_code

        # Generate unique short code
        for _ in range(10):
            candidate = self.generate_short_code(6)
            exists = await db.scalar(
                select(func.count(EmailTracking.id)).where(EmailTracking.short_code == candidate)
            )
            if not exists:
                row.short_code = candidate
                await db.flush()
                return candidate
        # Fallback to longer code if collisions
        row.short_code = self.generate_short_code(10)
        await db.flush()
        return row.short_code

    async def resolve_short_code(
        self,
        short_code: str,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Resolve a short URL code to its corresponding EmailTracking row.

        Args:
            short_code: The 6-8 char short code.
            db: Active database session.

        Returns:
            The matching EmailTracking row, or None.
        """
        if not short_code or len(short_code) > 16:
            return None
        return await db.scalar(
            select(EmailTracking).where(EmailTracking.short_code == short_code.strip())
        )

    # ------------------------------------------------------------------ #
    # QR/quishing identity resolution and Live scans
    # ------------------------------------------------------------------ #
    async def resolve_qr_identity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        email: str | None,
        username: str | None,
    ) -> tuple[HumanAsset | None, str]:
        """Resolve the identity entered on a QR portal.

        The contract is deliberately deterministic: e-mail wins, then the
        username/employee number.  Both lookups are case-insensitive and scoped
        to the campaign's organization.
        """
        email_normalized = (email or "").strip().lower()
        if email_normalized:
            employee = await db.scalar(
                select(HumanAsset)
                .where(
                    HumanAsset.organization_id == organization_id,
                    func.lower(HumanAsset.email) == email_normalized,
                )
                .order_by(HumanAsset.created_at.asc())
                .limit(1)
            )
            if employee is not None:
                return employee, IDENTITY_MATCHED_EMAIL

        username_normalized = (username or "").strip().lower()
        if username_normalized:
            employee = await db.scalar(
                select(HumanAsset)
                .where(
                    HumanAsset.organization_id == organization_id,
                    or_(
                        func.lower(func.coalesce(HumanAsset.username, ""))
                        == username_normalized,
                        func.lower(func.coalesce(HumanAsset.employee_id_external, ""))
                        == username_normalized,
                    ),
                )
                .order_by(HumanAsset.created_at.asc())
                .limit(1)
            )
            if employee is not None:
                return employee, IDENTITY_MATCHED_USERNAME

        return None, IDENTITY_UNKNOWN

    async def submit_qr_scan(
        self,
        db: AsyncSession,
        *,
        campaign_id: uuid.UUID,
        username: str,
        email: str,
        password_submitted: bool,
        fields: dict[str, str] | None,
        fingerprint_data: dict[str, Any] | None,
        ip_address: str | None,
        user_agent: str | None,
        tracking_uuid: uuid.UUID | str | None = None,
        client: dict[str, Any] | None = None,
    ) -> QRSubmissionResult | None:
        """Record a QR form submission, resolve its identity and apply -25 once.

        A tracking UUID is optional.  When present (the normal per-recipient
        poster flow), the matching tracking row is updated and the event is
        written to the interaction ledger.  When absent (a campaign-level QR
        link), the matching employee's tracking row is reused if one exists;
        otherwise the scan is still stored as an Unknown scan in ``qr_scans`` so
        an administrator can inspect the entered values and assign it later.

        The password value is never accepted by this method; only the
        ``password_submitted`` boolean reaches storage.
        """
        campaign = await db.get(EmailCampaign, campaign_id)
        if campaign is None:
            return None
        channel = (campaign.channel or "email").strip().lower()
        if channel != "qr":
            raise ValueError("QR submissions are only valid for qr campaigns")

        row: EmailTracking | None = None
        if tracking_uuid:
            uid = self._coerce_uuid(tracking_uuid)
            if uid is None:
                return None
            row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
            if row is None:
                return None
            if row.campaign_id != campaign.id:
                raise ValueError("tracking link does not belong to this campaign")
            if (row.channel or "").strip().lower() != "qr":
                raise ValueError("tracking link does not belong to a qr campaign")

        employee, resolution = await self.resolve_qr_identity(
            db,
            campaign.organization_id,
            email=email,
            username=username,
        )

        # Campaign-level links have no tracking UUID in the path.  Reuse the
        # resolved employee's existing recipient row when the launcher created
        # one; unknown visitors continue without a tracking row.
        if row is None and employee is not None:
            row = await db.scalar(
                select(EmailTracking).where(
                    EmailTracking.campaign_id == campaign.id,
                    EmailTracking.employee_id == employee.id,
                )
            )
            if row is not None and self._supports_for_update(db):
                row = await self._locked_tracking(db, EmailTracking.id, row.id)
            if row is not None and (row.channel or "").strip().lower() != "qr":
                row = None

        now = _now()
        first_time = row is not None and row.submitted_at is None
        # Deterministic SHA-256 over the canonical device evidence.  Stored
        # inside the fingerprint payload so the admin radar can group repeat
        # devices without ever exposing the raw canvas/WebGL strings.
        fingerprint_payload: dict[str, Any] = (
            dict(fingerprint_data) if isinstance(fingerprint_data, dict) else {}
        )
        if fingerprint_payload:
            canonical = json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            fingerprint_payload["fingerprint_hash"] = hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest()
        scan = QRScan(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            tracking_id=row.id if row is not None else None,
            employee_id=employee.id if employee is not None else None,
            username=username.strip()[:150] or None,
            email=email.strip().lower()[:255] or None,
            password_submitted=bool(password_submitted),
            identity_resolution=resolution,
            fingerprint_data=fingerprint_payload or None,
            ip_address=ip_address,
            user_agent=(user_agent or None) and user_agent[:2000],
            occurred_at=now,
        )
        db.add(scan)

        # Do not persist secret-looking form fields.  The password value is not
        # passed into this method at all; this guard covers a malicious client
        # that puts a password into ``fields``.
        safe_fields = sanitize_submitted_fields(fields or {})
        safe_fields.update(
            {
                "username": username.strip()[:MAX_FIELD_VALUE_LENGTH],
                "email": email.strip().lower()[:MAX_FIELD_VALUE_LENGTH],
                "password_submitted": "true" if password_submitted else "false",
            }
        )
        client_context: dict[str, Any] = {}
        if fingerprint_payload:
            client_context.update(fingerprint_payload)
        if isinstance(client, dict):
            client_context.update(client)

        elo_delta = 0
        penalty_applied = False
        if row is not None:
            row.submission_count = (row.submission_count or 0) + 1
            if first_time:
                row.submitted_at = now
            row.submitted_identifier = (email.strip().lower() or username.strip())[:255] or None
            row.submitted_username = username.strip()[:150] or None
            row.submitted_email = email.strip().lower()[:255] or None
            row.password_submitted = bool(password_submitted)
            # The new QR flow records a boolean only, never a length.
            row.password_length = None
            row.identity_resolution = resolution
            row.identity_resolved_employee_id = employee.id if employee is not None else None
            row.submitted_fields = safe_fields
            row.submitted_payload_encrypted = encrypt_payload(safe_fields)
            row.submitted_password_encrypted = None
            row.client_context = client_context or None
            row.last_ip_address = ip_address or row.last_ip_address
            row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
            await self._ensure_visit(db, row, now)

            if first_time and employee is not None and not row.qr_penalty_applied:
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1
                employee.last_test_date = now
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, QR_CREDENTIAL_ELO_DELTA
                )
                row.qr_penalty_applied = True
                penalty_applied = True
                elo_delta = QR_CREDENTIAL_ELO_DELTA

            self._record_interaction(
                db,
                row,
                EVENT_CREDENTIAL_SUBMITTED,
                now,
                ip_address,
                user_agent,
                {
                    "channel": "qr",
                    "submission_count": row.submission_count,
                    "field_names": sorted(safe_fields.keys()),
                    "password_submitted": bool(password_submitted),
                    "password_length": None,
                    "password_stored": False,
                    "identity_resolution": resolution,
                    "resolved_employee_id": (
                        str(employee.id) if employee is not None else None
                    ),
                    "resolved_employee_name": (
                        employee.full_name if employee is not None else None
                    ),
                    "submitted_username": row.submitted_username,
                    "submitted_email": row.submitted_email,
                    "elo_delta": elo_delta,
                    "qr_scan_id": str(scan.id),
                    "client": client_context,
                },
                payload_encrypted=row.submitted_payload_encrypted,
            )
        elif employee is not None:
            # There is no tracking row, but the entered identity is known.  The
            # penalty is still tied to the employee, once per campaign.
            prior_penalty = await db.scalar(
                select(QRScan.id)
                .where(
                    QRScan.campaign_id == campaign.id,
                    QRScan.employee_id == employee.id,
                    QRScan.penalty_applied.is_(True),
                )
                .limit(1)
            )
            if prior_penalty is None:
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1
                employee.last_test_date = now
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, QR_CREDENTIAL_ELO_DELTA
                )
                penalty_applied = True
                elo_delta = QR_CREDENTIAL_ELO_DELTA

        scan.elo_delta = elo_delta
        scan.penalty_applied = penalty_applied

        if employee is not None and (first_time or row is None) and penalty_applied:
            await db.flush()
            await self._classify(employee.id, db)

        await db.flush()
        logger.info(
            "qr_credential_submitted",
            tracking_uuid=str(row.tracking_uuid) if row is not None else None,
            campaign_id=str(campaign.id),
            scan_id=str(scan.id),
            identity_resolution=resolution,
            resolved_employee_id=str(employee.id) if employee is not None else None,
            password_submitted=bool(password_submitted),
            first_time=first_time,
            elo_delta=elo_delta,
        )
        return QRSubmissionResult(
            scan=scan,
            tracking=row,
            employee=employee,
            identity_resolution=resolution,
            elo_delta=elo_delta,
            first_time=first_time,
        )

    async def assign_qr_scan(
        self,
        scan_id: uuid.UUID,
        employee_id: uuid.UUID,
        db: AsyncSession,
        *,
        actor: str = "administrator",
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[QRScan, HumanAsset, bool] | None:
        """Manually link an unmatched scan to an employee.

        The once-only -25 QR penalty is applied to the assigned employee when
        no earlier scan in the same campaign already applied it.  Reassigning a
        scan never reverses or duplicates an existing penalty.
        """
        scan = await db.get(QRScan, scan_id)
        if scan is None:
            return None
        campaign = await db.get(EmailCampaign, scan.campaign_id)
        employee = await db.get(HumanAsset, employee_id)
        if campaign is None or employee is None:
            return None
        if employee.organization_id != campaign.organization_id:
            raise ValueError("employee belongs to another organization")

        penalty_applied = False
        elo_delta = 0
        if not scan.penalty_applied:
            prior_penalty = await db.scalar(
                select(QRScan.id)
                .where(
                    QRScan.campaign_id == scan.campaign_id,
                    QRScan.employee_id == employee.id,
                    QRScan.penalty_applied.is_(True),
                    QRScan.id != scan.id,
                )
                .limit(1)
            )
            if prior_penalty is None:
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1
                employee.last_test_date = scan.occurred_at or _now()
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, QR_CREDENTIAL_ELO_DELTA
                )
                penalty_applied = True
                elo_delta = QR_CREDENTIAL_ELO_DELTA
                await db.flush()
                await self._classify(employee.id, db)

        scan.employee_id = employee.id
        scan.identity_resolution = IDENTITY_MANUAL
        if penalty_applied:
            scan.penalty_applied = True
            scan.elo_delta = elo_delta

        tracking: EmailTracking | None = None
        if scan.tracking_id is not None:
            tracking = await db.get(EmailTracking, scan.tracking_id)
        if tracking is None:
            tracking = await db.scalar(
                select(EmailTracking).where(
                    EmailTracking.campaign_id == scan.campaign_id,
                    EmailTracking.employee_id == employee.id,
                )
            )
            if tracking is not None:
                scan.tracking_id = tracking.id

        if tracking is not None:
            tracking.identity_resolution = IDENTITY_MANUAL
            tracking.identity_resolved_employee_id = employee.id
            tracking.submitted_username = (
                tracking.submitted_username or scan.username
            )
            tracking.submitted_email = tracking.submitted_email or scan.email
            if tracking.submitted_at is None:
                tracking.submitted_at = scan.occurred_at
                tracking.submission_count = max(1, tracking.submission_count or 0)
                tracking.password_submitted = scan.password_submitted
            if penalty_applied:
                tracking.qr_penalty_applied = True
            self._record_interaction(
                db,
                tracking,
                EVENT_QR_IDENTITY_ASSIGNED,
                _now(),
                ip_address,
                user_agent,
                {
                    "scan_id": str(scan.id),
                    "employee_id": str(employee.id),
                    "employee_name": employee.full_name,
                    "actor": actor,
                    "elo_delta": elo_delta,
                },
            )

        await db.flush()
        logger.info(
            "qr_scan_assigned",
            scan_id=str(scan.id),
            employee_id=str(employee.id),
            actor=actor,
            penalty_applied=penalty_applied,
        )
        return scan, employee, penalty_applied

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

    async def _ensure_visit(
        self, db: AsyncSession, row: EmailTracking, now: datetime
    ) -> bool:
        """Backfill the open/click funnel markers without applying an Elo delta.

        The advanced channels have their own outcome-specific Elo rules, so a
        page visit must not also trigger the email channel's ``-32`` click
        penalty.  This helper only records that the recipient reached the
        simulation and returns ``True`` when this was the first visit.

        Args:
            db: Active session.
            row: Tracking row being updated.
            now: Event timestamp.

        Returns:
            ``True`` when the click marker was created by this call.
        """
        first_click = row.clicked_at is None
        if row.opened_at is None:
            row.opened_at = now
            row.open_count = (row.open_count or 0) + 1
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )
        if first_click:
            row.clicked_at = now
            row.click_count = (row.click_count or 0) + 1
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(clicked_count=EmailCampaign.clicked_count + 1)
            )
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.total_clicks = (employee.total_clicks or 0) + 1
                employee.last_test_date = now
        return first_click

    async def log_channel_visit(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
        *,
        channel: str,
    ) -> EmailTracking | None:
        """Record a neutral visit to a vishing/pretexting simulation page.

        This never changes the Elo rating.  The outcome endpoint applies the
        channel-specific reward or penalty once the recipient makes a choice.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            return None
        now = _now()
        first_click = await self._ensure_visit(db, row, now)
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        event_type = EVENT_QR_SCANNED if channel == "qr" else EVENT_CLICK
        self._record_interaction(
            db,
            row,
            event_type,
            now,
            ip_address,
            user_agent,
            {
                "channel": channel,
                "channel_visit": True,
                "first_click": first_click,
                "elo_delta": 0,
            },
        )
        await db.flush()
        return row

    async def log_qr_scan(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record a QR scan and return the row.

        A scan proves that the recipient followed a printed QR lure, but it is
        score-neutral: the printable poster leads to the simulated mobile
        sign-in page.  The quishing failure penalty is applied once, by
        :meth:`log_submission`, only after the recipient submits the form.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_qr_unknown", tracking_uuid=str(tracking_uuid))
            return None

        now = _now()
        first_click = await self._ensure_visit(db, row, now)
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        if first_click:
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, QR_SCAN_ELO_DELTA
                )
                await db.flush()
                await self._classify(employee.id, db)
        self._record_interaction(
            db,
            row,
            EVENT_QR_SCANNED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "qr",
                "first_scan": first_click,
                "elo_delta": QR_SCAN_ELO_DELTA if first_click else 0,
            },
        )
        await db.flush()
        logger.info(
            "qr_scanned",
            tracking_uuid=str(uid),
            first_scan=first_click,
        )
        return row

    async def log_usb_open(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record that a recipient opened the safe USB-drop document.

        The deliverable is placed outside a provider on a physical USB drive.
        A first open is a USB-specific failure: it costs ``-30`` Elo rather than
        the email click penalty.  Opening the same document again is idempotent
        for scoring but still appended to the ledger for evidence.

        The method deliberately refuses to score a tracking row that belongs to
        another channel, so a manually crafted ``/track/usb/...`` URL cannot
        penalise an unrelated email/QR recipient.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_usb_unknown", tracking_uuid=str(tracking_uuid))
            return None
        channel = (row.channel or "").strip().lower()
        if channel != "usb":
            logger.warning(
                "track_usb_channel_mismatch",
                tracking_uuid=str(uid),
                channel=channel or "unknown",
            )
            return row

        now = _now()
        first_open = await self._ensure_visit(db, row, now)
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        if first_open:
            employee = await db.get(HumanAsset, row.employee_id)
            if employee is not None:
                employee.elo_score = apply_elo_delta(
                    employee.elo_score, USB_OPEN_ELO_DELTA
                )
                await db.flush()
                await self._classify(employee.id, db)
        self._record_interaction(
            db,
            row,
            EVENT_USB_OPENED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "usb",
                "first_open": first_open,
                "elo_delta": USB_OPEN_ELO_DELTA if first_open else 0,
            },
        )
        await db.flush()
        logger.info(
            "usb_opened",
            tracking_uuid=str(uid),
            first_open=first_open,
        )
        return row

    async def log_channel_choice(
        self,
        tracking_uuid: uuid.UUID | str,
        channel: str,
        choice: str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
        *,
        client: dict[str, Any] | None = None,
    ) -> tuple[EmailTracking, bool] | None:
        """Record a vishing/pretexting outcome and apply its Elo rule.

        Choices are idempotent per tracking row: a recipient cannot farm Elo by
        pressing both buttons repeatedly.  ``reported_phish`` creates a real
        report-inbox row; the failure choices mark the simulation as submitted.

        Returns:
            ``(tracking_row, already_recorded)`` or ``None`` for an unknown link.

        Raises:
            ValueError: For a choice that does not belong to the channel.
        """
        channel = (channel or "").strip().lower()
        choice = (choice or "").strip().lower()
        allowed = {
            "vishing": {
                "credential_disclosed": EVENT_CREDENTIAL_DISCLOSED,
                "reported_phish": EVENT_REPORTED_PHISH,
            },
            "pretexting": {
                "financial_fraud": EVENT_FINANCIAL_FRAUD,
                "reported_phish": EVENT_REPORTED_PHISH,
            },
        }
        if channel not in allowed:
            raise ValueError(f"unsupported simulation channel: {channel!r}")
        if choice not in allowed[channel]:
            raise ValueError(f"invalid {channel} choice: {choice!r}")

        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning(
                "track_channel_choice_unknown",
                tracking_uuid=str(tracking_uuid),
                channel=channel,
            )
            return None
        if (row.channel or "email").strip().lower() != channel:
            raise ValueError(
                f"tracking link belongs to channel '{row.channel}', not '{channel}'"
            )

        event_type = allowed[channel][choice]
        # One link has exactly one outcome.  Checking every outcome event (not
        # only the pressed button) prevents a recipient from reporting and then
        # claiming the failure path, or from farming both rewards and penalties.
        existing = await db.scalar(
            select(TrainingInteraction.id).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type.in_(set(allowed[channel].values())),
            )
        )
        if existing is not None or row.reported_at is not None:
            return row, True

        employee = await db.get(HumanAsset, row.employee_id)
        if employee is None:  # pragma: no cover - FK guarantees existence
            return None

        now = _now()
        await self._ensure_visit(db, row, now)
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        if client:
            row.client_context = client

        if choice == "reported_phish":
            delta = (
                VISHING_REPORT_ELO_DELTA
                if channel == "vishing"
                else PRETEXTING_REPORT_ELO_DELTA
            )
            row.reported_at = now
            employee.total_reports = (employee.total_reports or 0) + 1
            report = PhishingReport(
                organization_id=employee.organization_id,
                employee_id=employee.id,
                reported_email_subject=(
                    "Simulated vishing call (training)"
                    if channel == "vishing"
                    else "Simulated executive pretexting message (training)"
                ),
                reported_sender=None,
                description=(
                    "Recipient recognised the simulated phone call and reported it."
                    if channel == "vishing"
                    else "Recipient recognised the simulated executive request and reported it."
                ),
                status="new",
                is_training_simulation=True,
                details={
                    "tracking_uuid": str(row.tracking_uuid),
                    "campaign_id": str(row.campaign_id),
                    "source": channel,
                    "choice": choice,
                },
            )
            db.add(report)
        else:
            delta = (
                VISHING_CREDENTIAL_ELO_DELTA
                if channel == "vishing"
                else PRETEXTING_FRAUD_ELO_DELTA
            )
            if row.submitted_at is None:
                row.submitted_at = now
            row.submission_count = (row.submission_count or 0) + 1
            if channel == "vishing":
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1

        employee.elo_score = apply_elo_delta(employee.elo_score, delta)
        self._record_interaction(
            db,
            row,
            event_type,
            now,
            ip_address,
            user_agent,
            {
                "channel": channel,
                "choice": choice,
                "elo_delta": delta,
                "client": client or {},
            },
        )
        await db.flush()
        await self._classify(employee.id, db)
        logger.info(
            "channel_choice_recorded",
            tracking_uuid=str(uid),
            channel=channel,
            choice=choice,
            elo_score=employee.elo_score,
        )
        return row, False

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
