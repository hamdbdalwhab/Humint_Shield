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
from datetime import datetime, timedelta, timezone
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
from app.services.enterprise_identity_service import enterprise_identity_service
from app.services.elo_engine import (
    QR_REPEAT_EVASION_ELO_DELTA,
    QR_SCAN_ELO_DELTA,
    SMS_CREDENTIAL_ELO_DELTA,
    apply_elo_delta,
    clamp_elo,
    smart_elo_delta,
)
from app.services.employee_service import (
    apply_elo_action,
    campaign_difficulty,
    tracking_difficulty,
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

#: A second scan of the same poster from the same device (IP + User-Agent)
#: within this window is the same interaction, not a new one.
QR_DUPLICATE_SCAN_WINDOW_SECONDS = 90
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
EVENT_USB_DEVICE_PROBE = "usb_device_probe"
EVENT_CREDENTIAL_DISCLOSED = "credential_disclosed"
EVENT_FINANCIAL_FRAUD = "financial_fraud"
EVENT_REPORTED_PHISH = "reported_phish"
EVENT_QR_IDENTITY_ASSIGNED = "qr_identity_assigned"
EVENT_SMS_SENT = "sms_sent"
EVENT_SMS_CLICKED = "sms_clicked"
EVENT_SMS_SUBMITTED = "sms_credential_submitted"
EVENT_WHATSAPP_SENT = "whatsapp_sent"
EVENT_WHATSAPP_READ = "whatsapp_read"
EVENT_WHATSAPP_REPLIED = "whatsapp_replied"
EVENT_WHATSAPP_CLICKED = "whatsapp_clicked"
EVENT_WHATSAPP_SESSION_STATUS = "whatsapp_session_status"

#: WhatsApp reply classification.  Disclosing information to an unknown sender
#: costs Elo; pushing back / reporting it earns Elo.
WHATSAPP_REPLY_PENALTY = 15
WHATSAPP_REPLY_REWARD = 10

#: Vocabulary of a reply that hands information to the attacker.
WHATSAPP_DISCLOSURE_KEYWORDS: tuple[str, ...] = (
    "password",
    "passcode",
    "otp",
    "verification code",
    "code is",
    "pin",
    "cvv",
    "card number",
    "iban",
    "account number",
    "transfer",
    "wire",
    "here it is",
    "i will send",
    "yes i did",
)

#: Vocabulary of a reply that challenges or reports the lure.
WHATSAPP_SUSPICION_KEYWORDS: tuple[str, ...] = (
    "phishing",
    "scam",
    "fraud",
    "suspicious",
    "spam",
    "report",
    "who are you",
    "not me",
    "did not request",
    "didn't request",
    "verify with it",
    "call the helpdesk",
    "blocked",
    "not clicking",
    "security team",
)


def classify_whatsapp_reply(text: str | None) -> tuple[str, int]:
    """Classify a recipient's WhatsApp reply and return ``(category, delta)``.

    Categories:
        ``disclosed``  – the reply shares a secret or agrees to transfer money
            (``-15`` Elo);
        ``suspicious`` – the reply challenges or reports the message
            (``+10`` Elo);
        ``neutral``    – anything else (``0``).
    """
    lowered = (text or "").strip().lower()
    if not lowered:
        return "neutral", 0
    if any(keyword in lowered for keyword in WHATSAPP_DISCLOSURE_KEYWORDS):
        return "disclosed", -WHATSAPP_REPLY_PENALTY
    if any(keyword in lowered for keyword in WHATSAPP_SUSPICION_KEYWORDS):
        return "suspicious", WHATSAPP_REPLY_REWARD
    return "neutral", 0
EVENT_VISHING_CALL_PLACED = "vishing_call_placed"
EVENT_VISHING_CALL_ANSWERED = "vishing_call_answered"
EVENT_VISHING_CALL_COMPLETED = "vishing_call_completed"
EVENT_VISHING_CALL_FAILED = "vishing_call_failed"
#: The phone rang but nobody picked up before the carrier ended the call.  This
#: is a recipient-side outcome, not a system error, so it is tracked apart from
#: :data:`EVENT_VISHING_CALL_FAILED`.
EVENT_VISHING_CALL_NOT_ANSWERED = "vishing_call_not_answered"
EVENT_VISHING_TTS_PLAYED = "vishing_tts_played"

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
#: Hard limits for the endpoint telemetry a browser can send with a USB open.
MAX_TELEMETRY_DEPTH = 4
MAX_TELEMETRY_ITEMS = 120
MAX_TELEMETRY_KEY_LENGTH = 64
MAX_TELEMETRY_STRING = 400
MAX_TELEMETRY_LIST = 24


def sanitize_telemetry(raw: object, _depth: int = 0, _budget: list[int] | None = None) -> dict[str, Any]:
    """Return a bounded, JSON-safe copy of browser telemetry.

    The payload comes from an untrusted document, so nothing is stored verbatim:
    nesting depth, entry count, key length, string length and list length are all
    capped.  Scalars are kept as they are so the dashboard can render them
    without a second parse.

    Args:
        raw: Whatever the client sent (usually a decoded JSON object).
        _depth: Current recursion depth (internal).
        _budget: Remaining entry budget (internal).

    Returns:
        A sanitised mapping; ``{}`` when the input is not a mapping.
    """
    if not isinstance(raw, dict) or _depth > MAX_TELEMETRY_DEPTH:
        return {}
    budget = _budget if _budget is not None else [MAX_TELEMETRY_ITEMS]
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        if budget[0] <= 0:
            break
        name = str(key)[:MAX_TELEMETRY_KEY_LENGTH]
        if value is None:
            continue
        budget[0] -= 1
        if isinstance(value, bool | int | float):
            clean[name] = value
        elif isinstance(value, str):
            clean[name] = value[:MAX_TELEMETRY_STRING]
        elif isinstance(value, dict):
            nested = sanitize_telemetry(value, _depth + 1, budget)
            if nested:
                clean[name] = nested
        elif isinstance(value, list | tuple):
            items: list[Any] = []
            for item in list(value)[:MAX_TELEMETRY_LIST]:
                if isinstance(item, str):
                    items.append(item[:MAX_TELEMETRY_STRING])
                elif isinstance(item, bool | int | float):
                    items.append(item)
                elif isinstance(item, dict) and _depth < MAX_TELEMETRY_DEPTH:
                    nested = sanitize_telemetry(item, _depth + 1, budget)
                    if nested:
                        items.append(nested)
            if items:
                clean[name] = items
    return clean


#: Fields the optional local identity tool may report.  The probe endpoint is
#: public (the tracking UUID is the only secret), so the stored shape is a fixed
#: whitelist instead of whatever JSON arrives.
IDENTITY_PROBE_TEXT_FIELDS: tuple[str, ...] = (
    "username",
    "user_domain",
    "logged_on_user",
    "hostname",
    "domain",
    "workgroup",
    "os_caption",
    "os_version",
    "os_build",
    "os_arch",
    "manufacturer",
    "model",
    "serial",
    "cpu",
    "local_ip",
    "mac",
    "gateway",
    "dns_servers",
    "session_name",
    "powershell",
    "timezone",
)
IDENTITY_PROBE_NUMBER_FIELDS: tuple[str, ...] = (
    "cpu_cores",
    "cpu_logical",
    "ram_gb",
    "uptime_minutes",
)
IDENTITY_PROBE_BOOL_FIELDS: tuple[str, ...] = ("is_admin",)
IDENTITY_PROBE_MAX_TEXT = 200


def sanitize_identity_probe(raw: object) -> dict[str, Any]:
    """Return a bounded, whitelisted copy of the local tool's report.

    Args:
        raw: The decoded request body.

    Returns:
        Only known identity fields, truncated to a display-safe length; ``{}``
        when nothing usable was sent.
    """
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in IDENTITY_PROBE_TEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, str):
            text = value.replace("\x00", "").strip()[:IDENTITY_PROBE_MAX_TEXT]
            if text:
                clean[key] = text
        elif isinstance(value, bool | int | float):
            clean[key] = str(value)[:IDENTITY_PROBE_MAX_TEXT]
    for key in IDENTITY_PROBE_NUMBER_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            clean[key] = value
        elif isinstance(value, str):
            try:
                clean[key] = float(value)
            except ValueError:
                continue
    for key in IDENTITY_PROBE_BOOL_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool):
            clean[key] = value
    event_id = raw.get("client_event_id")
    if isinstance(event_id, str) and event_id.strip():
        clean["client_event_id"] = event_id.strip()[:64]
    collected_at = raw.get("collected_at")
    if isinstance(collected_at, str) and collected_at.strip():
        clean["collected_at"] = collected_at.strip()[:40]
    return clean


def merge_telemetry(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge new telemetry over the stored packet without losing known facts.

    Each open replaces the values it can observe, but a later, smaller packet
    (a retry, an older copy of the document, a link-preview fetch) must never
    erase a richer profile captured minutes earlier.  Incoming values win where
    present; everything else is kept.
    """
    merged: dict[str, Any] = dict(existing or {})
    for key, value in (incoming or {}).items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = merge_telemetry(current, value)
        elif value in (None, "", {}, []):
            merged.setdefault(key, value)
        else:
            merged[key] = value
    return merged


def telemetry_summary(telemetry: dict[str, Any] | None) -> dict[str, Any]:
    """Return the display-sized subset of a telemetry payload.

    The ledger ``details`` column and the live board only need the forensic
    headline (which machine, which network, where from), not the whole packet.
    """
    data = telemetry or {}
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    screen = data.get("screen") if isinstance(data.get("screen"), dict) else {}
    network = data.get("network") if isinstance(data.get("network"), dict) else {}
    gpu = data.get("gpu") if isinstance(data.get("gpu"), dict) else {}
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    server = data.get("server") if isinstance(data.get("server"), dict) else {}
    summary = {
        "fingerprint": data.get("fingerprint"),
        "client_event_id": data.get("client_event_id"),
        "platform": device.get("ua_platform") or device.get("platform"),
        "platform_version": device.get("ua_platform_version"),
        "architecture": device.get("ua_architecture"),
        "model": device.get("ua_model"),
        "user_agent": device.get("user_agent"),
        "language": device.get("language"),
        "timezone": device.get("timezone"),
        "cpu_cores": device.get("hardware_concurrency"),
        "memory_gb": device.get("device_memory_gb"),
        "screen": (
            f"{screen.get('width')}x{screen.get('height')}"
            if screen.get("width") and screen.get("height")
            else None
        ),
        "pixel_ratio": screen.get("pixel_ratio"),
        "gpu": gpu.get("renderer"),
        "online": network.get("online"),
        "effective_type": network.get("effective_type"),
        "downlink_mbps": network.get("downlink_mbps"),
        "rtt_ms": network.get("rtt_ms"),
        "source_path": source.get("path") or source.get("href"),
        "opened_at": source.get("opened_at"),
        "ip": server.get("ip"),
        "country": server.get("country"),
        "city": server.get("city"),
        "isp": server.get("isp"),
        "latitude": server.get("latitude"),
        "longitude": server.get("longitude"),
    }
    return {key: value for key, value in summary.items() if value not in (None, "")}


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
    async def log_vishing_event(
        self,
        tracking_uuid: uuid.UUID | str,
        event_type: str,
        db: AsyncSession,
        *,
        details: dict[str, Any] | None = None,
        provider_message_id: str | None = None,
        delivery_status: str | None = None,
        delivery_error: str | None = None,
    ) -> EmailTracking | None:
        """Record one real vishing call lifecycle event.

        The call-control provider is IllyVoIP.  ``provider_message_id`` is the
        provider's ``call_control_id`` and is indexed on the tracking row so a
        later status/hangup request can be correlated back to the campaign.

        Args:
            tracking_uuid: Per-recipient tracking UUID.
            event_type: One of the ``EVENT_VISHING_*`` constants.
            db: Active session.
            details: Non-secret call context (state, status, duration).
            provider_message_id: IllyVoIP ``call_control_id``.
            delivery_status: Provider-neutral status (``calling``,
                ``answered``, ``completed`` or ``failed``).
            delivery_error: Last provider error, when the call failed.

        Returns:
            The updated row, or ``None`` when the UUID is unknown.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning(
                "vishing_track_unknown", tracking_uuid=str(tracking_uuid)
            )
            return None

        now = _now()
        row.provider = "illyvoip"
        row.event_type = event_type
        if provider_message_id:
            row.provider_message_id = provider_message_id[:255]
        if delivery_status:
            row.delivery_status = delivery_status[:20]
        if delivery_error is not None:
            row.delivery_error = delivery_error[:500]
        if event_type in {
            EVENT_VISHING_CALL_PLACED,
            EVENT_VISHING_CALL_ANSWERED,
        }:
            row.sent_at = row.sent_at or now
        if event_type == EVENT_VISHING_CALL_ANSWERED:
            row.delivered_at = row.delivered_at or now
        if event_type == EVENT_VISHING_CALL_COMPLETED:
            row.completed_at = row.completed_at or now
        if event_type in {
            EVENT_VISHING_CALL_FAILED,
            EVENT_VISHING_CALL_NOT_ANSWERED,
        }:
            row.failed_at = row.failed_at or now

        # TrainingInteraction.employee_id is non-null; campaign tracking rows
        # always have an employee, but a malformed legacy row must not break
        # the provider call after it has already been placed.
        if row.employee_id is not None:
            self._record_interaction(
                db,
                row,
                event_type,
                now,
                ip_address=None,
                user_agent=None,
                details=details or {},
            )
        return row

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

        elo_delta = 0
        if first_open:
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )
            employee = (
                await db.get(HumanAsset, row.employee_id)
                if row.employee_id is not None
                else None
            )
            if employee is not None:
                elo_delta = await apply_elo_action(db, employee, row, "opened")
        self._record_interaction(
            db,
            row,
            EVENT_OPEN,
            now,
            ip_address,
            user_agent,
            {
                "open_count": row.open_count,
                "first_open": first_open,
                "elo_delta": elo_delta,
            },
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

        elo_delta = 0
        if first_click:
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(clicked_count=EmailCampaign.clicked_count + 1)
            )
            difficulty = await tracking_difficulty(db, row)
            elo_delta = smart_elo_delta(row.channel, "clicked", difficulty)
            await self._adjust_employee(
                db,
                row.employee_id,
                delta=-CLICK_PENALTY,
                increment_clicks=first_click,
                elo_delta=elo_delta,
            )
        self._record_interaction(
            db,
            row,
            EVENT_CLICK,
            now,
            ip_address,
            user_agent,
            {
                "click_count": row.click_count,
                "first_click": first_click,
                "elo_delta": elo_delta,
            },
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
                elo_delta = await apply_elo_action(db, employee, row, "submitted")
            await db.flush()
            target_id = (
                (employee.email if employee else None)
                or identifier
                or f"Phish-Victim-{str(uid)[:8]}"
            )
            try:
                containment_rep = await enterprise_identity_service.execute_containment(
                    target_identity=target_id,
                    breach_type="credential_submission",
                    tracking_uuid=str(uid),
                    context={
                        "ip_address": ip_address,
                        "channel": channel,
                        "identifier": identifier,
                    },
                )
                curr_ctx = dict(row.client_context or {})
                curr_ctx["containment_report"] = containment_rep.to_dict()
                row.client_context = curr_ctx
            except Exception as c_exc:
                logger.warning("submission_auto_containment_failed", error=str(c_exc))

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
                elo_delta = await apply_elo_action(db, employee, row, "submitted")
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
                        HumanAsset.email.ilike(f"{username_normalized}@%"),
                    ),
                )
                .order_by(HumanAsset.created_at.asc())
                .limit(1)
            )
            if employee is not None:
                return employee, IDENTITY_MATCHED_USERNAME

        return None, IDENTITY_UNKNOWN

    async def log_campaign_qr_scan(
        self,
        campaign: EmailCampaign,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> tuple[EmailTracking, QRScan] | None:
        """Record an anonymous QR scan from a printed poster encoding the campaign ID.

        Two kinds of traffic are deliberately not new interactions:

        * **link-preview fetchers** (WhatsApp, Telegram, Slack, crawlers) that
          fetch the URL only to render a preview — counting them would add a
          phantom scan every time the poster URL is pasted into a chat, and
        * **repeat scans** from the same device (same IP and User-Agent)
          inside :data:`QR_DUPLICATE_SCAN_WINDOW_SECONDS`, which are the same
          person re-opening the same poster.

        Returns ``None`` for a preview fetch so the caller can redirect without
        creating a row; a duplicate returns the original tracking/scan pair.
        """
        from app.services.device_detector import detect_device_model, is_preview_bot

        if is_preview_bot(user_agent):
            logger.info(
                "qr_campaign_scan_preview_ignored",
                campaign_id=str(campaign.id),
                user_agent=(user_agent or "")[:120],
            )
            return None

        now = _now()
        if ip_address or user_agent:
            recent_filters = [
                QRScan.campaign_id == campaign.id,
                QRScan.occurred_at
                >= now - timedelta(seconds=QR_DUPLICATE_SCAN_WINDOW_SECONDS),
            ]
            if ip_address:
                recent_filters.append(QRScan.ip_address == ip_address)
            if user_agent:
                recent_filters.append(QRScan.user_agent == user_agent[:2000])
            previous = (
                await db.execute(
                    select(QRScan)
                    .where(*recent_filters)
                    .order_by(QRScan.occurred_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if previous is not None and previous.tracking_id is not None:
                existing = await db.get(EmailTracking, previous.tracking_id)
                if existing is not None:
                    logger.info(
                        "qr_campaign_scan_duplicate_ignored",
                        campaign_id=str(campaign.id),
                        scan_id=str(previous.id),
                        tracking_uuid=str(existing.tracking_uuid),
                    )
                    return existing, previous

        tracking = EmailTracking(
            campaign_id=campaign.id,
            employee_id=None,
            tracking_uuid=uuid.uuid4(),
            template_id=campaign.template_id,
            channel="qr",
            event_type="qr_scanned",
            opened_at=now,
            clicked_at=now,
            click_count=1,
            last_ip_address=ip_address,
            last_user_agent=(user_agent or "")[:2000] or None,
        )
        db.add(tracking)
        await db.flush()

        from app.services.geoip_service import lookup_ip_geolocation

        dev_model = detect_device_model(user_agent)
        geo_info = await lookup_ip_geolocation(ip_address)
        initial_events = [{
            "event": "qr_scanned",
            "label": "مسح رمز الاستجابة السريعة (QR)",
            "timestamp": now.isoformat(),
            "time_str": now.strftime("%H:%M:%S"),
        }]

        scan = QRScan(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            tracking_id=tracking.id,
            employee_id=None,
            event_type="qr_scanned",
            identity_resolution="unknown",
            password_submitted=False,
            penalty_applied=False,
            elo_delta=0,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:2000] or None,
            device_model=dev_model,
            country=geo_info.country,
            city=geo_info.city,
            isp=geo_info.isp,
            latitude=geo_info.latitude,
            longitude=geo_info.longitude,
            real_time_events=initial_events,
            occurred_at=now,
        )
        db.add(scan)
        await db.flush()


        logger.info(
            "qr_campaign_scanned",
            campaign_id=str(campaign.id),
            tracking_uuid=str(tracking.tracking_uuid),
            scan_id=str(scan.id),
        )
        return tracking, scan

    async def record_qr_probe(
        self,
        db: AsyncSession,
        *,
        campaign_id: uuid.UUID,
        tracking_uuid: uuid.UUID | str | None = None,
        fingerprint_data: dict[str, Any] | None = None,
        telemetry: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> QRScan | None:
        """Process an immediate background probe from the QR landing page.

        Captures WebRTC local IP, router/mDNS name, GPU renderer, and high-entropy
        hardware specs without requiring the user to submit credentials yet.
        """
        now = _now()
        merged_fp = dict(fingerprint_data or {})
        if telemetry:
            merged_fp.update(telemetry)

        from app.services.device_detector import detect_device_model
        from app.services.geoip_service import lookup_ip_geolocation

        gps_data = merged_fp.get("gps") if isinstance(merged_fp, dict) else None
        dev_model = detect_device_model(user_agent, fingerprint_data=merged_fp)
        dev_real_name = (
            merged_fp.get("device_real_name")
            or merged_fp.get("hostname")
            or (telemetry and telemetry.get("device_real_name"))
        )
        if dev_real_name and dev_model:
            if dev_real_name.lower() != dev_model.lower() and dev_model.lower() not in dev_real_name.lower():
                dev_model = f"{dev_real_name} ({dev_model})"
            else:
                dev_model = dev_real_name

        geo_info = await lookup_ip_geolocation(ip_address, client_gps=gps_data)

        local_ip = merged_fp.get("local_ip") or (telemetry and telemetry.get("local_ip"))
        mDNS_name = merged_fp.get("mDNS_name") or (telemetry and telemetry.get("mDNS_name"))
        gpu_renderer = (
            merged_fp.get("gpu_renderer")
            or merged_fp.get("webgl_renderer")
            or (telemetry and telemetry.get("gpu_renderer"))
        )
        hw_fp = (
            merged_fp.get("hardware_fingerprint")
            or merged_fp.get("fingerprint_hash")
            or (telemetry and telemetry.get("hardware_fingerprint"))
        )
        cpu_cores = merged_fp.get("cpu_cores") or (telemetry and telemetry.get("cpu_cores"))
        device_memory_gb = merged_fp.get("device_memory_gb") or (telemetry and telemetry.get("device_memory_gb"))
        screen_resolution = (
            merged_fp.get("screen")
            or merged_fp.get("screen_resolution")
            or (telemetry and telemetry.get("screen_resolution"))
        )
        pixel_ratio = merged_fp.get("pixel_ratio") or (telemetry and telemetry.get("pixel_ratio"))
        language = merged_fp.get("language") or (telemetry and telemetry.get("language"))

        clean_context: dict[str, Any] = {
            "hardware_fingerprint": hw_fp,
            "device_real_name": dev_real_name or dev_model,
            "device_model": dev_model,
            "local_ip": local_ip,
            "mDNS_name": mDNS_name,
            "gpu_renderer": gpu_renderer,
            "cpu_cores": cpu_cores,
            "device_memory_gb": device_memory_gb,
            "screen_resolution": screen_resolution,
            "pixel_ratio": pixel_ratio,
            "language": language,
            "user_agent": (user_agent or "")[:400],
            "city": geo_info.city,
            "country": geo_info.country,
            "isp": geo_info.isp,
            "latitude": geo_info.latitude,
            "longitude": geo_info.longitude,
        }
        clean_context = {k: v for k, v in clean_context.items() if v is not None}

        # Find matching EmailTracking row
        tracking: EmailTracking | None = None
        if tracking_uuid:
            try:
                t_uid = uuid.UUID(str(tracking_uuid))
                tracking = await db.scalar(
                    select(EmailTracking).where(EmailTracking.tracking_uuid == t_uid)
                )
            except ValueError:
                pass

        if tracking is None:
            tracking = await db.scalar(
                select(EmailTracking)
                .where(
                    EmailTracking.campaign_id == campaign_id,
                    EmailTracking.channel == "qr",
                )
                .order_by(EmailTracking.opened_at.desc())
                .limit(1)
            )

        # Find matching QRScan row
        scan: QRScan | None = None
        if tracking is not None:
            scan = await db.scalar(
                select(QRScan)
                .where(QRScan.tracking_id == tracking.id)
                .order_by(QRScan.occurred_at.desc())
                .limit(1)
            )

        if scan is None:
            scan = await db.scalar(
                select(QRScan)
                .where(QRScan.campaign_id == campaign_id)
                .order_by(QRScan.occurred_at.desc())
                .limit(1)
            )

        if scan is not None:
            scan.device_model = dev_model or scan.device_model
            scan.fingerprint_data = clean_context
            scan.country = geo_info.country or scan.country
            scan.city = geo_info.city or scan.city
            scan.isp = geo_info.isp or scan.isp
            if geo_info.latitude is not None:
                scan.latitude = geo_info.latitude
            if geo_info.longitude is not None:
                scan.longitude = geo_info.longitude
            if ip_address and ip_address not in ("127.0.0.1", "::1", "unknown"):
                scan.ip_address = ip_address

            events = list(scan.real_time_events or [])
            if not any(ev.get("event") == "probe_received" for ev in events):
                events.append({
                    "event": "probe_received",
                    "label": "استخراج بصمة العتاد وبيانات الراوتر الحية",
                    "timestamp": now.isoformat(),
                    "time_str": now.strftime("%H:%M:%S"),
                })
                scan.real_time_events = events
        else:
            campaign = await db.get(EmailCampaign, campaign_id)
            if campaign is None:
                return None
            scan = QRScan(
                organization_id=campaign.organization_id,
                campaign_id=campaign.id,
                tracking_id=tracking.id if tracking else None,
                employee_id=tracking.employee_id if tracking else None,
                event_type="qr_scanned",
                identity_resolution="unknown",
                password_submitted=False,
                penalty_applied=False,
                elo_delta=0,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:2000] or None,
                device_model=dev_model,
                country=geo_info.country,
                city=geo_info.city,
                isp=geo_info.isp,
                latitude=geo_info.latitude,
                longitude=geo_info.longitude,
                fingerprint_data=clean_context,
                real_time_events=[
                    {
                        "event": "probe_received",
                        "label": "استخراج بصمة العتاد وبيانات الراوتر الحية",
                        "timestamp": now.isoformat(),
                        "time_str": now.strftime("%H:%M:%S"),
                    }
                ],
                occurred_at=now,
            )
            db.add(scan)

        if tracking is not None:
            tracking.client_context = clean_context
            if ip_address and ip_address not in ("127.0.0.1", "::1", "unknown"):
                tracking.last_ip_address = ip_address

        await db.flush()
        return scan

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
        """Record a QR form submission, enforce Device Binding & Anti-Evasion, and apply Elo deltas.

        A tracking UUID is optional. When present, the matching tracking row is updated.
        When absent, the matching employee's tracking row is reused if one exists.
        
        ANTI-EVASION / DEVICE BINDING LOGIC:
        1. Extract or generate canonical hardware_fingerprint. Fallback to SHA256(UserAgent + IP).
        2. Query prior scans to check if this hardware_fingerprint was previously bound to an employee.
        3. Rules:
           - Rule A (First Scan): New device. Link to entered employee, deduct standard -25 Elo.
           - Rule B (Repeat Scan - Different Email): Device exists, but entered email is different!
             Evasion attempt: keep device owner as employee, apply EXTRA -15 Elo penalty to owner,
             flag as evasion_attempt in metadata.
           - Rule C (Repeat Scan - Same Email): Device exists and matches entered email.
             Update timestamp, record repeat scan with scan_count.
           - Rule D (Unknown Employee entered on known device):
             BLOCK assignment to unknown email, bind to device owner, flag as evasion_attempt,
             and apply -15 Elo penalty to owner.
        """
        campaign = await db.get(EmailCampaign, campaign_id)
        if campaign is None:
            return None
        channel = (campaign.channel or "email").strip().lower()
        if channel != "qr":
            raise ValueError("QR submissions are only valid for qr campaigns")

        now = _now()

        # Step 1: Extract / Generate canonical hardware_fingerprint with fallback
        fingerprint_payload: dict[str, Any] = (
            dict(fingerprint_data) if isinstance(fingerprint_data, dict) else {}
        )
        hw_fp = (
            fingerprint_payload.get("hardware_fingerprint")
            or fingerprint_payload.get("fingerprint_hash")
            or (client and client.get("hardware_fingerprint"))
        )
        if not hw_fp or not str(hw_fp).strip():
            # Fallback SHA256(UserAgent + IP) if client fingerprint blocked/failed
            raw_fallback = f"{(user_agent or '').strip()}|{(ip_address or '').strip()}"
            hw_fp = hashlib.sha256(raw_fallback.encode("utf-8")).hexdigest()

        hw_fp = str(hw_fp).strip()
        fingerprint_payload["hardware_fingerprint"] = hw_fp
        fingerprint_payload["fingerprint_hash"] = hw_fp

        # Step 2: Query database for prior device binding in this organization
        prior_scans = (
            await db.execute(
                select(QRScan)
                .where(
                    QRScan.organization_id == campaign.organization_id,
                    QRScan.employee_id.is_not(None),
                )
                .order_by(QRScan.occurred_at.asc())
            )
        ).scalars().all()

        device_owner: HumanAsset | None = None
        for ps in prior_scans:
            ps_fp = (ps.fingerprint_data or {}).get("hardware_fingerprint") or (ps.fingerprint_data or {}).get("fingerprint_hash")
            if ps_fp and str(ps_fp).strip() == hw_fp and ps.employee_id:
                device_owner = await db.get(HumanAsset, ps.employee_id)
                if device_owner is not None:
                    break

        if device_owner is None:
            prior_trackings = (
                await db.execute(
                    select(EmailTracking)
                    .where(
                        EmailTracking.campaign_id == campaign.id,
                        EmailTracking.employee_id.is_not(None),
                    )
                    .order_by(EmailTracking.opened_at.asc())
                )
            ).scalars().all()
            for pt in prior_trackings:
                ctx = pt.client_context or {}
                pt_fp = ctx.get("hardware_fingerprint") or ctx.get("fingerprint_hash")
                if pt_fp and str(pt_fp).strip() == hw_fp and pt.employee_id:
                    device_owner = await db.get(HumanAsset, pt.employee_id)
                    if device_owner is not None:
                        break

        # Step 3: Resolve entered identity
        entered_employee, raw_resolution = await self.resolve_qr_identity(
            db,
            campaign.organization_id,
            email=email,
            username=username,
        )

        entered_email_clean = (email or "").strip().lower()
        entered_user_clean = (username or "").strip()
        owner_email_clean = (device_owner.email or "").strip().lower() if device_owner else ""

        is_evasion = False
        is_repeat_same = False
        status_flag = "first_scan"
        repeat_status_msg: str | None = None
        scan_count = 1

        if device_owner is not None:
            # Device is ALREADY bound to a known employee
            is_same = (
                (entered_employee is not None and entered_employee.id == device_owner.id)
                or (entered_email_clean and entered_email_clean == owner_email_clean)
            )
            if is_same:
                # Rule C (Repeat Scan - Same Email)
                is_repeat_same = True
                status_flag = "repeat_scan"
                employee = device_owner
                resolution = "repeat_scan"
                elo_delta = 0
                penalty_applied = False
                prior_count = (
                    await db.scalar(
                        select(func.count(QRScan.id)).where(
                            QRScan.campaign_id == campaign.id,
                            QRScan.employee_id == device_owner.id,
                        )
                    )
                    or 0
                )
                scan_count = prior_count + 1
                repeat_status_msg = f"⚠️ تكرار مسح - الجهاز مسجل باسم {device_owner.full_name} (المسح رقم {scan_count})"
            else:
                # Rule B & Rule D (Repeat Scan - Different / Unknown Email -> Evasion / Framing)
                is_evasion = True
                status_flag = "evasion_attempt"
                # Keep original employee_id linked to that device
                employee = device_owner
                resolution = "evasion_attempt"
                elo_delta = QR_REPEAT_EVASION_ELO_DELTA  # -15
                employee.elo_score = apply_elo_delta(employee.elo_score, elo_delta)
                employee.total_credential_submissions = (employee.total_credential_submissions or 0) + 1
                employee.last_test_date = now
                penalty_applied = True
                repeat_status_msg = f"⚠️ محاولة تهرب / انتحال - الجهاز مسجل باسم {device_owner.full_name}"
        else:
            # Device is NEW
            if entered_employee is not None:
                # Rule A (First Scan)
                employee = entered_employee
                resolution = raw_resolution
                status_flag = "first_scan"
                qr_difficulty = await campaign_difficulty(db, campaign)
                elo_delta = smart_elo_delta("qr", "submitted", qr_difficulty)
                employee.elo_score = apply_elo_delta(employee.elo_score, elo_delta)
                employee.total_credential_submissions = (employee.total_credential_submissions or 0) + 1
                employee.last_test_date = now
                penalty_applied = True
            else:
                # Unknown visitor
                employee = None
                resolution = "unknown"
                status_flag = "external_visitor"
                elo_delta = 0
                penalty_applied = False

        # Load or create EmailTracking row
        row: EmailTracking | None = None
        if tracking_uuid:
            uid = self._coerce_uuid(tracking_uuid)
            if uid is not None:
                row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
                if row is not None and row.campaign_id == campaign.id and (row.channel or "").strip().lower() == "qr":
                    pass
                else:
                    row = None

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

        if row is None:
            row = await db.scalar(
                select(EmailTracking)
                .where(
                    EmailTracking.campaign_id == campaign.id,
                    EmailTracking.employee_id.is_(None),
                    EmailTracking.channel == "qr",
                )
                .order_by(EmailTracking.opened_at.desc())
                .limit(1)
            )
            if row is not None and employee is not None:
                row.employee_id = employee.id

        if row is None:
            row = EmailTracking(
                campaign_id=campaign.id,
                employee_id=employee.id if employee is not None else None,
                tracking_uuid=uuid.uuid4(),
                template_id=campaign.template_id,
                channel="qr",
                opened_at=now,
                clicked_at=now,
                click_count=1,
                last_ip_address=ip_address,
                last_user_agent=(user_agent or "")[:2000] or None,
            )
            db.add(row)
            await db.flush()

        first_time = row.submitted_at is None

        # Device detector & GeoIP
        from app.services.device_detector import detect_device_model
        from app.services.geoip_service import lookup_ip_geolocation

        gps_data = fingerprint_payload.get("gps") if isinstance(fingerprint_payload, dict) else None
        dev_model = detect_device_model(user_agent, fingerprint_data=fingerprint_payload)
        dev_real_name = (
            fingerprint_payload.get("device_real_name")
            or fingerprint_payload.get("hostname")
            or (client and client.get("device_real_name"))
        )
        if dev_real_name and dev_model:
            if dev_real_name.lower() != dev_model.lower() and dev_model.lower() not in dev_real_name.lower():
                dev_model = f"{dev_real_name} ({dev_model})"
            else:
                dev_model = dev_real_name
            fingerprint_payload["device_real_name"] = dev_real_name
        geo_info = await lookup_ip_geolocation(ip_address, client_gps=gps_data)

        # Sanitize metadata JSONB to bounded, essential keys only (Step 4 hardening)
        clean_context: dict[str, Any] = {
            "hardware_fingerprint": hw_fp,
            "device_real_name": dev_real_name or dev_model,
            "device_model": dev_model,
            "local_ip": fingerprint_payload.get("local_ip") or (client and client.get("local_ip")),
            "mDNS_name": fingerprint_payload.get("mDNS_name") or (client and client.get("mDNS_name")),
            "gpu_renderer": fingerprint_payload.get("gpu_renderer") or fingerprint_payload.get("webgl_renderer") or (client and client.get("gpu_renderer")),
            "cpu_cores": fingerprint_payload.get("cpu_cores") or (client and client.get("cpu_cores")),
            "device_memory_gb": fingerprint_payload.get("device_memory_gb") or (client and client.get("device_memory_gb")),
            "screen_resolution": fingerprint_payload.get("screen") or fingerprint_payload.get("screen_resolution") or (client and client.get("screen_resolution")),
            "pixel_ratio": fingerprint_payload.get("pixel_ratio") or (client and client.get("pixel_ratio")),
            "language": fingerprint_payload.get("language") or (client and client.get("language")),
            "user_agent": (user_agent or "")[:400],
            "city": geo_info.city,
            "country": geo_info.country,
            "isp": geo_info.isp,
            "status": status_flag,
            "repeat_status": repeat_status_msg,
            "scan_count": scan_count,
            "entered_email": entered_email_clean if (is_evasion or employee is None) else None,
            "entered_username": entered_user_clean if (is_evasion or employee is None) else None,
            "device_owner_id": str(device_owner.id) if device_owner else None,
            "device_owner_name": device_owner.full_name if device_owner else None,
        }
        clean_context = {k: v for k, v in clean_context.items() if v is not None}

        # Create new QRScan record for this submission
        scan = QRScan(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            tracking_id=row.id,
            employee_id=employee.id if employee is not None else None,
            username=entered_user_clean[:150] or None,
            email=entered_email_clean[:255] or None,
            password_submitted=bool(password_submitted),
            identity_resolution=resolution,
            event_type="qr_submitted",
            fingerprint_data=clean_context,
            elo_delta=elo_delta,
            penalty_applied=penalty_applied,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:2000] or None,
            device_model=dev_model,
            country=geo_info.country,
            city=geo_info.city,
            isp=geo_info.isp,
            latitude=geo_info.latitude,
            longitude=geo_info.longitude,
            occurred_at=now,
        )
        
        timeline_label = "تسجيل بيانات"
        if is_evasion:
            timeline_label = f"محاولة تهرب (جهاز {device_owner.full_name if device_owner else ''})"
        elif is_repeat_same:
            timeline_label = f"تكرار مسح (رقم {scan_count})"

        scan.real_time_events = [
            {
                "event": "form_submitted",
                "label": timeline_label,
                "timestamp": now.isoformat(),
                "time_str": now.strftime("%H:%M:%S"),
                "status": status_flag,
            }
        ]
        db.add(scan)

        # Form fields sanitized
        safe_fields = sanitize_submitted_fields(fields or {})
        safe_fields.update(
            {
                "username": entered_user_clean[:MAX_FIELD_VALUE_LENGTH],
                "email": entered_email_clean[:MAX_FIELD_VALUE_LENGTH],
                "password_submitted": "true" if password_submitted else "false",
            }
        )

        # Update EmailTracking row
        if employee is not None:
            row.employee_id = employee.id
        row.submission_count = (row.submission_count or 0) + 1
        if first_time:
            row.submitted_at = now
        row.submitted_identifier = (entered_email_clean or entered_user_clean)[:255] or None
        row.submitted_username = entered_user_clean[:150] or None
        row.submitted_email = entered_email_clean[:255] or None
        row.password_submitted = bool(password_submitted)
        row.password_length = None
        row.identity_resolution = resolution
        row.identity_resolved_employee_id = employee.id if employee is not None else None
        row.submitted_fields = safe_fields
        row.submitted_payload_encrypted = encrypt_payload(safe_fields)
        row.client_context = clean_context
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        row.event_type = "qr_submitted"
        if penalty_applied:
            row.qr_penalty_applied = True
        await self._ensure_visit(db, row, now)

        if employee is not None:
            self._record_interaction(
                db,
                row,
                "qr_credential_submitted",
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
                    "resolved_employee_id": str(employee.id),
                    "resolved_employee_name": employee.full_name,
                    "submitted_username": row.submitted_username,
                    "submitted_email": row.submitted_email,
                    "elo_delta": elo_delta,
                    "qr_scan_id": str(scan.id),
                    "client": clean_context,
                },
                payload_encrypted=row.submitted_payload_encrypted,
            )

        if employee is not None and penalty_applied:
            await db.flush()
            await self._classify(employee.id, db)

        await db.flush()

        logger.info(
            "qr_credential_submitted",
            tracking_uuid=str(row.tracking_uuid),
            campaign_id=str(campaign.id),
            scan_id=str(scan.id),
            identity_resolution=resolution,
            resolved_employee_id=str(employee.id) if employee is not None else None,
            password_submitted=bool(password_submitted),
            first_time=first_time,
            elo_delta=elo_delta,
            status=status_flag,
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
                qr_difficulty = await campaign_difficulty(db, campaign)
                elo_delta = smart_elo_delta("qr", "submitted", qr_difficulty)
                employee.elo_score = apply_elo_delta(employee.elo_score, elo_delta)
                penalty_applied = True
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
        elo_delta = await apply_elo_action(db, employee, row, "reported")
        self._record_interaction(
            db,
            row,
            EVENT_REPORTED,
            now,
            ip_address,
            user_agent,
            {"source": "training_page", "elo_delta": elo_delta},
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
        # A report is a positive security behaviour.  The reward was applied
        # above via the smart channel/difficulty engine; the ``reported_at``
        # guard makes the whole operation idempotent.
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

        elo_delta = 0
        if not was_reported:
            employee.total_reports = (employee.total_reports or 0) + 1
            elo_delta = await apply_elo_action(db, employee, row, "reported")
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
        # The report reward is applied once.  A row already reported through the
        # public training page has already earned it; an administrator marking
        # that same report safe must not grant it a second time.
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
                "elo_delta": elo_delta,
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
                # The submission itself is scored with the smart "submitted"
                # impact in ``log_submission``.  Do not also apply a click
                # penalty here: a direct form submission is one outcome.

    # ------------------------------------------------------------------ #
    # WhatsApp events
    # ------------------------------------------------------------------ #
    async def log_whatsapp_sent(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        *,
        provider: str = "wa-akg",
        message_id: str | None = None,
        characters: int = 0,
    ) -> EmailTracking | None:
        """Append ``whatsapp_sent`` evidence for an accepted message.

        Acceptance is not delivery: ``delivered_at``/``read_at`` are only set by
        the WA-AKG webhook, never here.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("whatsapp_sent_unknown", tracking_uuid=str(tracking_uuid))
            return None
        now = _now()
        row.provider = provider
        if message_id and not row.provider_message_id:
            row.provider_message_id = str(message_id)[:255]
        self._record_interaction(
            db,
            row,
            EVENT_WHATSAPP_SENT,
            now,
            row.last_ip_address,
            row.last_user_agent,
            {
                "channel": "whatsapp",
                "provider": provider,
                "message_id": message_id,
                "characters": characters,
                "elo_delta": 0,
            },
        )
        await db.flush()
        logger.info(
            "whatsapp_sent_logged",
            tracking_uuid=str(uid),
            provider=provider,
            message_id=message_id,
        )
        return row

    async def log_whatsapp_click(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record that a recipient followed the WhatsApp tracking link.

        Following the link is score-neutral; the failure outcome is the lure
        form, exactly like SMS.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_whatsapp_unknown", tracking_uuid=str(tracking_uuid))
            return None
        now = _now()
        first_click = await self._ensure_visit(db, row, now)
        if not first_click:
            # ``clicked_at`` keeps the first-click time (the funnel must not
            # move), but every repeat click is counted so the live board and the
            # reports show real activity instead of a frozen "1".
            row.click_count = (row.click_count or 0) + 1
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        self._record_interaction(
            db,
            row,
            EVENT_WHATSAPP_CLICKED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "whatsapp",
                "first_click": first_click,
                "elo_delta": 0,
            },
        )
        await db.flush()
        logger.info("whatsapp_clicked", tracking_uuid=str(uid), first_click=first_click)
        return row

    async def log_whatsapp_read(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        *,
        message_id: str | None = None,
    ) -> EmailTracking | None:
        """Record a WhatsApp read receipt (``message.read`` webhook).

        Reading is score-neutral; the ledger keeps the exact timestamp so the
        operator can tell "sent" from "read".
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            return None
        now = _now()
        if row.read_at is None:
            row.read_at = now
            row.delivery_status = "read"
        if message_id and not row.provider_message_id:
            row.provider_message_id = str(message_id)[:255]
        self._record_interaction(
            db,
            row,
            EVENT_WHATSAPP_READ,
            now,
            row.last_ip_address,
            row.last_user_agent,
            {"channel": "whatsapp", "message_id": message_id, "elo_delta": 0},
        )
        await db.flush()
        logger.info("whatsapp_read", tracking_uuid=str(uid), message_id=message_id)
        return row

    async def log_whatsapp_reply(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        *,
        text: str | None,
        phone: str | None = None,
        message_id: str | None = None,
    ) -> tuple[EmailTracking, str, int] | None:
        """Record a WhatsApp reply and score the recipient's response.

        The reply body itself is **not** persisted (it may contain real secrets);
        only its length, the classification and the Elo delta are stored.

        Returns:
            ``(row, category, elo_delta)`` or ``None`` for an unknown link.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("whatsapp_reply_unknown", tracking_uuid=str(tracking_uuid))
            return None
        category, delta = classify_whatsapp_reply(text)
        now = _now()
        if row.read_at is None:
            row.read_at = now
        row.delivery_status = "replied" if delta >= 0 else "replied_disclosed"
        if message_id and not row.provider_message_id:
            row.provider_message_id = str(message_id)[:255]
        if delta:
            employee = (
                await db.get(HumanAsset, row.employee_id) if row.employee_id else None
            )
            if employee is not None:
                employee.elo_score = apply_elo_delta(employee.elo_score, delta)
        self._record_interaction(
            db,
            row,
            EVENT_WHATSAPP_REPLIED,
            now,
            row.last_ip_address,
            row.last_user_agent,
            {
                "channel": "whatsapp",
                "phone": phone,
                "message_id": message_id,
                "reply_length": len((text or "").strip()),
                "reply_category": category,
                "elo_delta": delta,
            },
        )
        await db.flush()
        logger.info(
            "whatsapp_replied",
            tracking_uuid=str(uid),
            category=category,
            elo_delta=delta,
        )
        return row, category, delta

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

    async def log_sms_sent(
        self,
        tracking_uuid: uuid.UUID | str,
        db: AsyncSession,
        *,
        provider: str,
        batch_id: str | None,
        characters: int,
    ) -> EmailTracking | None:
        """Append ``sms_sent`` evidence for an accepted SMS.

        ``provider`` acceptance is not delivery: the delivery timestamp is only
        set by the gateway callback/poll, mirroring the email channel.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            return None
        now = _now()
        self._record_interaction(
            db,
            row,
            EVENT_SMS_SENT,
            now,
            row.last_ip_address,
            row.last_user_agent,
            {
                "channel": "sms",
                "provider": provider,
                "batch_id": batch_id,
                "characters": characters,
                "elo_delta": 0,
            },
        )
        await db.flush()
        logger.info(
            "sms_sent",
            tracking_uuid=str(uid),
            provider=provider,
            batch_id=batch_id,
        )
        return row

    async def log_sms_click(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> EmailTracking | None:
        """Record that a recipient opened the link in a simulated SMS.

        The click is score-neutral on purpose: the smishing penalty belongs to
        the credential form on the landing page, not to following a link.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("track_sms_unknown", tracking_uuid=str(tracking_uuid))
            return None
        now = _now()
        first_click = await self._ensure_visit(db, row, now)
        if not first_click:
            # ``clicked_at`` keeps the first-click time (the funnel must not
            # move), but every repeat click is counted so the live board and the
            # reports show real activity instead of a frozen "1".
            row.click_count = (row.click_count or 0) + 1
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        self._record_interaction(
            db,
            row,
            EVENT_SMS_CLICKED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "sms",
                "first_click": first_click,
                "elo_delta": 0,
            },
        )
        await db.flush()
        logger.info("sms_clicked", tracking_uuid=str(uid), first_click=first_click)
        return row

    async def log_sms_submission(
        self,
        tracking_uuid: uuid.UUID | str,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
        *,
        identifier: str | None = None,
        password_length: int | None = None,
    ) -> tuple[EmailTracking, bool] | None:
        """Record a credential submission on the SMS landing page.

        Idempotent per tracking row: the ``-40`` smishing penalty is applied
        once, however many times the form is submitted.

        Returns:
            ``(tracking_row, already_recorded)`` or ``None`` for an unknown link.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning(
                "track_sms_submit_unknown", tracking_uuid=str(tracking_uuid)
            )
            return None
        existing = await db.scalar(
            select(TrainingInteraction.id).where(
                TrainingInteraction.tracking_id == row.id,
                TrainingInteraction.event_type == EVENT_SMS_SUBMITTED,
            )
        )
        now = _now()
        if existing is not None:
            # The form was submitted again.  The -40 penalty stays once-only,
            # but the attempt must still exist as evidence: a repeat submission
            # is exactly the behaviour the training page is meant to reveal.
            row.last_ip_address = ip_address or row.last_ip_address
            row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
            self._record_interaction(
                db,
                row,
                EVENT_SMS_SUBMITTED,
                now,
                ip_address,
                user_agent,
                {
                    "channel": "sms",
                    "repeat": True,
                    "elo_delta": 0,
                    "submission_index": row.submission_count,
                    "store": "discarded",
                },
            )
            await db.flush()
            return row, True

        employee = await db.get(HumanAsset, row.employee_id)
        if employee is None:  # pragma: no cover - FK guarantees existence
            return None

        first_click = await self._ensure_visit(db, row, now)
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None
        # Keep the evidence the recipient will see: the typed identifier (for a
        # masked display) and the password *length* only.  The password value
        # itself is never stored.
        clean_identifier = (identifier or "").strip()[:255]
        if clean_identifier:
            row.submitted_identifier = clean_identifier
        if password_length is not None and password_length > 0:
            row.password_length = int(password_length)
            row.password_submitted = True

        employee.elo_score = apply_elo_delta(
            employee.elo_score, SMS_CREDENTIAL_ELO_DELTA
        )
        employee.total_credential_submissions = (
            employee.total_credential_submissions or 0
        ) + 1
        if row.submitted_at is None:
            row.submitted_at = now
        row.submission_count = (row.submission_count or 0) + 1

        self._record_interaction(
            db,
            row,
            EVENT_SMS_SUBMITTED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "sms",
                "first_click": first_click,
                "elo_delta": SMS_CREDENTIAL_ELO_DELTA,
                "submission_index": row.submission_count,
                "store": "discarded",
            },
        )
        await self._classify(employee.id, db)
        await db.flush()
        logger.info(
            "sms_credential_submitted",
            tracking_uuid=str(uid),
            employee_id=str(employee.id),
            elo=employee.elo_score,
        )
        return row, False

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
        *,
        hostname: str | None = None,
        username: str | None = None,
        domain: str | None = None,
        arch: str | None = None,
        scenario: str | None = None,
        attack_type: str | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> EmailTracking | None:
        """Record that a recipient opened the safe USB-drop document or triggered HID.

        The deliverable is placed outside a provider on a physical USB drive.
        A first open is scored with the USB channel weight: a normal bait is a
        click-level failure and HID execution is a submission-level failure.
        Opening the same document again is idempotent for scoring but still
        appended to the ledger for evidence.

        ``telemetry`` is the optional forensic packet the document itself sends
        (device, screen, GPU, network, timezone, source path, GPS, server-side
        GeoIP).  It is sanitised, stored on the tracking row and echoed in the
        ledger so the live board can show *which machine* opened the file.  A
        client retry is recognised by its ``client_event_id`` and is not counted
        twice.
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
        clean_telemetry = sanitize_telemetry(telemetry)
        client_context = dict(row.client_context or {})

        # A retried beacon is the same open, not a second one.  The id is
        # generated by the document and kept for the last 20 packets.
        event_id = clean_telemetry.get("client_event_id")
        seen_ids = [str(item) for item in (client_context.get("usb_event_ids") or [])]
        if event_id and str(event_id) in seen_ids:
            logger.info(
                "usb_open_duplicate_ignored",
                tracking_uuid=str(uid),
                client_event_id=str(event_id),
            )
            return row

        if clean_telemetry:
            device = clean_telemetry.get("device")
            device = device if isinstance(device, dict) else {}
            hostname = hostname or device.get("hostname")
            username = username or device.get("username")
            domain = domain or device.get("domain")
            arch = arch or device.get("ua_architecture")
            if event_id:
                seen_ids.append(str(event_id))
                client_context["usb_event_ids"] = seen_ids[-20:]
            previous_telemetry = client_context.get("usb_telemetry")
            client_context["usb_telemetry"] = merge_telemetry(
                previous_telemetry if isinstance(previous_telemetry, dict) else None,
                clean_telemetry,
            )
            client_context["device_fingerprint"] = (
                clean_telemetry.get("fingerprint")
                or client_context.get("device_fingerprint")
            )
            source = clean_telemetry.get("source")
            if isinstance(source, dict) and source:
                client_context["usb_source"] = source
            server = clean_telemetry.get("server")
            if isinstance(server, dict) and server:
                client_context["geo"] = {
                    key: server.get(key)
                    for key in ("country", "city", "isp", "latitude", "longitude")
                    if server.get(key) is not None
                }

        device_summary = telemetry_summary(clean_telemetry)
        if device_summary.get("source_path"):
            source_path = str(device_summary["source_path"])
            client_context["source_path"] = source_path[:500]
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        # A physical open is an *open*, not a click: nobody followed a link.
        # Only the open markers are set so the board shows the truthful stage.
        first_open = row.opened_at is None
        if row.opened_at is None:
            row.opened_at = now
        row.open_count = (row.open_count or 0) + 1
        if first_open:
            await db.execute(
                update(EmailCampaign)
                .where(EmailCampaign.id == row.campaign_id)
                .values(opened_count=EmailCampaign.opened_count + 1)
            )

        is_hid = str(attack_type or "").lower() in ("hid", "badusb")
        actual_attack_type = "badusb_hid" if is_hid else "baiting"
        elo_penalty = 0

        if hostname:
            client_context["hostname"] = hostname
        if username:
            client_context["username"] = username
        if domain:
            client_context["domain"] = domain
        if arch:
            client_context["arch"] = arch
        if scenario:
            client_context["scenario"] = scenario
        client_context["attack_type"] = actual_attack_type

        # Log to breach event log for real-time live radar
        breaches = list(client_context.get("breach_events") or [])
        breaches.append({
            "hostname": hostname or "UNKNOWN-HOST",
            "username": username or "Unknown User",
            "domain": domain or "",
            "arch": arch or "",
            "scenario": scenario or ("HID Keystroke Injection" if is_hid else ""),
            "attack_type": actual_attack_type,
            "ip_address": ip_address,
            "timestamp": now.isoformat(),
            "device": device_summary,
            "source_path": device_summary.get("source_path"),
        })
        client_context["breach_events"] = breaches[-50:]
        row.client_context = client_context

        if row.employee_id is None and (username or hostname):
            campaign = await db.get(EmailCampaign, row.campaign_id)
            if campaign:
                matched_emp, _ = await self.resolve_qr_identity(
                    db,
                    campaign.organization_id,
                    email=None,
                    username=username or hostname,
                )
                if matched_emp:
                    row.employee_id = matched_emp.id

        if first_open:
            employee = await db.get(HumanAsset, row.employee_id) if row.employee_id else None
            if employee is not None:
                # A normal USB bait is a click-level failure; HID execution is
                # equivalent to a credential submission and scores as such.
                elo_penalty = await apply_elo_action(
                    db, employee, row, "submitted" if is_hid else "clicked"
                )
                await db.flush()
                await self._classify(employee.id, db)
            target_id = (
                (employee.email if employee else None)
                or username
                or hostname
                or f"USB-Endpoint-{str(uid)[:8]}"
            )
            try:
                containment_rep = await enterprise_identity_service.execute_containment(
                    target_identity=target_id,
                    breach_type=actual_attack_type,
                    tracking_uuid=str(uid),
                    context={
                        "hostname": hostname,
                        "username": username,
                        "ip_address": ip_address,
                        "attack_type": actual_attack_type,
                        "channel": "usb",
                    },
                )
                client_context["containment_report"] = containment_rep.to_dict()
                row.client_context = client_context
            except Exception as c_exc:
                logger.warning("usb_auto_containment_failed", error=str(c_exc))
        self._record_interaction(
            db,
            row,
            "hid_executed" if is_hid else EVENT_USB_OPENED,
            now,
            ip_address,
            user_agent,
            {
                "channel": "usb",
                "first_open": first_open,
                "elo_delta": elo_penalty if first_open else 0,
                "hostname": hostname,
                "username": username,
                "attack_type": actual_attack_type,
                "device": device_summary,
                "source_path": device_summary.get("source_path"),
                "ip_address": ip_address,
            },
        )
        await db.flush()
        logger.info(
            "usb_opened",
            tracking_uuid=str(uid),
            first_open=first_open,
            device_platform=device_summary.get("platform"),
            device_city=device_summary.get("city"),
            telemetry_present=bool(clean_telemetry),
        )
        return row

    async def log_usb_device_probe(
        self,
        tracking_uuid: uuid.UUID | str,
        payload: dict[str, Any] | None,
        ip_address: str | None,
        user_agent: str | None,
        db: AsyncSession,
    ) -> tuple[EmailTracking | None, bool]:
        """Attach the local identity tool's report to a USB tracking row.

        The HTML document can never read the Windows account or the machine's
        real name; the optional collector can, and posts it here.  This is
        enrichment, not a new failure, so it neither increments the open count
        nor applies another Elo penalty.

        Returns:
            ``(row, recorded)``.  ``recorded`` is ``False`` for a retry, an
            unknown link or a row that belongs to another channel.
        """
        uid = self._coerce_uuid(tracking_uuid)
        if uid is None:
            return None, False
        row = await self._locked_tracking(db, EmailTracking.tracking_uuid, uid)
        if row is None:
            logger.warning("usb_probe_unknown", tracking_uuid=str(tracking_uuid))
            return None, False
        channel = (row.channel or "").strip().lower()
        if channel not in ("", "usb"):
            logger.warning(
                "usb_probe_channel_mismatch",
                tracking_uuid=str(uid),
                channel=channel,
            )
            return row, False

        identity = sanitize_identity_probe(payload)
        if not identity:
            return row, False

        now = _now()
        client_context = dict(row.client_context or {})
        event_id = identity.get("client_event_id")
        seen_ids = [
            str(item) for item in (client_context.get("usb_probe_event_ids") or [])
        ]
        if event_id and str(event_id) in seen_ids:
            logger.info(
                "usb_probe_duplicate_ignored",
                tracking_uuid=str(uid),
                client_event_id=str(event_id),
            )
            return row, False
        if event_id:
            seen_ids.append(str(event_id))
            client_context["usb_probe_event_ids"] = seen_ids[-20:]

        telemetry = dict(client_context.get("usb_telemetry") or {})
        telemetry["local_probe"] = {
            "source": "local_tool",
            "identity": identity,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "received_at": now.isoformat(),
        }
        client_context["usb_telemetry"] = telemetry
        client_context["identity_source"] = "local_tool"
        hostname = identity.get("hostname")
        username = identity.get("username")
        if hostname:
            client_context["hostname"] = hostname
            client_context["device_real_name"] = hostname
        if username:
            client_context["username"] = username
        domain = identity.get("domain") or identity.get("workgroup")
        if domain:
            client_context["domain"] = domain
        row.last_ip_address = ip_address or row.last_ip_address
        row.last_user_agent = (user_agent or row.last_user_agent or "")[:2000] or None

        if row.employee_id is None and (username or hostname):
            campaign = await db.get(EmailCampaign, row.campaign_id)
            if campaign:
                matched_emp, _ = await self.resolve_qr_identity(
                    db,
                    campaign.organization_id,
                    email=None,
                    username=username or hostname,
                )
                if matched_emp:
                    row.employee_id = matched_emp.id

        row.client_context = client_context
        self._record_interaction(
            db,
            row,
            EVENT_USB_DEVICE_PROBE,
            now,
            ip_address,
            user_agent,
            {
                "channel": "usb",
                "source": "local_tool",
                "hostname": hostname,
                "username": username,
                "domain": domain,
                "os_build": identity.get("os_build"),
                "model": identity.get("model"),
                "is_admin": identity.get("is_admin"),
            },
        )
        await db.flush()
        logger.info(
            "usb_device_probe_recorded",
            tracking_uuid=str(uid),
            hostname=hostname,
            username_present=bool(username),
        )
        return row, True

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
            delta = await apply_elo_action(db, employee, row, "reported")
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
            delta = await apply_elo_action(db, employee, row, "submitted")
            if row.submitted_at is None:
                row.submitted_at = now
            row.submission_count = (row.submission_count or 0) + 1
            if channel == "vishing":
                employee.total_credential_submissions = (
                    employee.total_credential_submissions or 0
                ) + 1

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
