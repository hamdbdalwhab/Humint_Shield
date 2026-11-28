"""Real outbound vishing calls through the IllyVoIP Voice API.

This module is the only place that talks to IllyVoIP.  It implements the
documented call-control workflow:

1. ``POST /api/v1/voice/call-control/calls`` creates the outbound call.
2. ``POST /api/v1/voice/call-control/status`` is polled until the call is
   answered or reaches a terminal state.
3. ``POST /api/v1/voice/call-control/speak`` synthesises and plays the script
   with the native Voice API TTS engine.
4. ``POST /api/v1/voice/call-control/wait`` keeps the call open for the
   estimated playback duration.
5. ``POST /api/v1/voice/call-control/hangup`` ends the call.

No call is simulated.  Every mutation is sent to IllyVoIP with an
``Idempotency-Key`` derived from the campaign and tracking identifiers, so a
retry after a network error cannot place a second call or charge the script
twice.  The API key is read from settings and is never logged.

Provider limitations are surfaced rather than hidden.  The Voice API TTS
catalog exposes many languages; the service passes the resolved
language/voice to IllyVoIP and never substitutes browser-side speech
synthesis.  When the caller does not choose a language, the script itself
decides: Arabic text is spoken with the configured Arabic language
(``ar-AR`` by default) instead of the English default, which would read the
same text as gibberish.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Strict E.164: plus sign, non-zero country code, 8-15 digits total.
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
#: Caller IDs are numeric; IllyVoIP accepts them with or without a leading +.
CALLER_ID_RE = re.compile(r"^\+?[1-9]\d{6,14}$")
#: Arabic script blocks, used to pick the TTS language from the script text.
_ARABIC_SCRIPT_RE = re.compile(
    "[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

_ANSWERED_STATES = frozenset(
    {
        "active",
        "answered",
        "bridged",
        "connected",
        "in-progress",
        "in_progress",
        "talking",
    }
)
#: States that prove the destination equipment is alerting the person.
_RINGING_STATES = frozenset({"ringing", "ring", "alerting", "progress", "early_media"})
_TERMINAL_STATES = frozenset(
    {
        "busy",
        "canceled",
        "cancelled",
        "completed",
        "disconnected",
        "ended",
        "failed",
        "hangup",
        "no-answer",
        "no_answer",
    }
)
_PLACEHOLDER_PREFIXES = (
    "your",
    "change-me",
    "change_me",
    "example",
    "placeholder",
    "todo",
    "<",
)
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class IllyVoIPError(RuntimeError):
    """Base class for every IllyVoIP failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        fields: dict[str, Any] | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.fields = fields or {}
        self.retryable = retryable
        self.retry_after = retry_after


class IllyVoIPConfigurationError(IllyVoIPError):
    """Raised when the real vishing channel is not fully configured."""


class IllyVoIPValidationError(IllyVoIPError):
    """Raised when a caller supplies an invalid phone number or script."""


class IllyVoIPTransportError(IllyVoIPError):
    """Raised when the HTTP transport fails before IllyVoIP responds."""


class IllyVoIPAPIError(IllyVoIPError):
    """Raised when IllyVoIP returns an error response."""


class IllyVoIPContentReviewError(IllyVoIPAPIError):
    """Raised for ``403 voice_content_review_required``.

    The rejected text is not charged or played.  ``review_reference`` is the
    identifier shown in the IllyVoIP Communication reviews screen.
    """

    def __init__(
        self,
        message: str,
        *,
        review_reference: str | None = None,
        status_code: int | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code="voice_content_review_required",
            fields=fields,
            retryable=False,
        )
        self.review_reference = review_reference


class IllyVoIPTimeoutError(IllyVoIPError):
    """Raised when a bounded call-control operation exceeds its deadline."""


class IllyVoIPCallFailedError(IllyVoIPError):
    """Raised when a call reaches a terminal state before it is answered."""


#: An answer that arrives faster than this after ringing started is almost
#: certainly a carrier announcement, voicemail or IVR - not a person picking up.
MIN_PLAUSIBLE_HUMAN_ANSWER_SECONDS = 1.0


@dataclass(slots=True)
class AnswerObservation:
    """What the provider actually showed between dialling and answer.

    ``answered_at`` alone does not prove a person answered: IllyVoIP documents
    that it cannot distinguish a human from an answering machine, and a carrier
    announcement also produces an answered session.  Recording whether the call
    ever rang, and how long the answer took, is what lets the system report the
    truth instead of claiming an acknowledgement that never happened.
    """

    rang: bool = False
    observed_ringing: bool = False
    ring_seconds: float | None = None
    answer_delay_seconds: float | None = None
    suspect_auto_answer: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return asdict(self)


@dataclass(slots=True)
class IllyVoIPCallResult:
    """The outcome of one completed real vishing call."""

    call_control_id: str
    state: str
    call_status: str
    answered_at: str | None = None
    ended_at: str | None = None
    failure_reason: str | None = None
    tts_media: str | None = None
    tts_charge: dict[str, Any] | None = None
    hangup: dict[str, Any] | None = None
    duration_seconds: float = 0.0
    #: Whether the destination actually rang (a ``ringing`` state was observed).
    rang: bool = False
    #: Seconds between the first ringing observation and the answer.
    answer_delay_seconds: float | None = None
    #: ``True`` when the answer looked automatic (voicemail/announcement/IVR).
    answer_suspect_auto: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation for API responses."""
        return asdict(self)


def is_e164_phone(value: str | None) -> bool:
    """Return ``True`` when ``value`` is a valid E.164 phone number."""
    return bool(value and E164_RE.fullmatch(value.strip()))


def _is_placeholder(value: str | None) -> bool:
    """Return ``True`` for blank or obvious documentation placeholders."""
    text = (value or "").strip()
    if not text:
        return True
    lower = text.lower()
    return lower.startswith(_PLACEHOLDER_PREFIXES) or lower in {
        "none",
        "null",
        "n/a",
        "na",
    }


def mask_phone(phone: str | None) -> str:
    """Mask a phone number for logs while retaining the country prefix."""
    digits = (phone or "").lstrip("+")
    if len(digits) <= 6:
        return "***"
    return f"+{digits[:4]}***{digits[-2:]}"


def _clean_optional(value: str | None) -> str:
    """Strip an optional string and treat placeholders as absent."""
    text = (value or "").strip()
    return "" if _is_placeholder(text) else text


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a numeric ``Retry-After`` header, ignoring HTTP-date values."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        return None


def _normalize_base_url(raw: str) -> str:
    """Validate and normalise the IllyVoIP API base URL."""
    base = (raw or "").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IllyVoIPConfigurationError(
            "ILLYVOIP_API_BASE_URL must be an absolute http(s) URL"
        )
    return base


def _normalize_recipient(value: str | None) -> str:
    """Validate a destination number and return it in E.164 form."""
    phone = re.sub(r"[\s\-()]", "", (value or "").strip())
    if not E164_RE.fullmatch(phone):
        raise IllyVoIPValidationError(
            "recipient phone must be in E.164 format (for example +966500000000)"
        )
    return phone


def _normalize_caller_id(value: str | None) -> str:
    """Validate a caller ID and return the numeric form IllyVoIP expects."""
    raw = re.sub(r"[\s\-()]", "", (value or "").strip())
    if not CALLER_ID_RE.fullmatch(raw):
        raise IllyVoIPValidationError(
            "caller ID must be a verified numeric caller ID (7-15 digits, "
            "with or without a leading +)"
        )
    return raw.lstrip("+")


def _validate_call_control_id(value: str | None) -> str:
    """Validate the opaque call-control identifier returned by IllyVoIP."""
    call_id = (value or "").strip()
    if not call_id or len(call_id) > 255:
        raise IllyVoIPValidationError("call_control_id is required")
    return call_id


def detect_tts_language(
    text: str | None, *, default: str, arabic: str | None = None
) -> str:
    """Return the TTS language implied by ``text``.

    An Arabic script handed to an ``en-US`` voice is read as unintelligible
    noise, so the script decides the language whenever the caller did not pick
    one.  English or numeric-only scripts keep ``default``.

    Args:
        text: The script that will be spoken.
        default: Language to use for non-Arabic text.
        arabic: Language to use for Arabic text (falls back to ``default``).

    Returns:
        The language code to send to IllyVoIP.
    """
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if letters:
        arabic_letters = sum(1 for ch in letters if _ARABIC_SCRIPT_RE.match(ch))
        # Mixed scripts (Arabic plus English product names) still count as
        # Arabic: two out of five letters is already enough to need an Arabic
        # voice.
        if arabic_letters * 5 >= len(letters) * 2:
            return arabic or default
    return default


def _validate_script(text: str | None) -> str:
    """Validate the TTS script against the provider's 2,000-character limit."""
    script = (text or "").strip()
    if not script:
        raise IllyVoIPValidationError("TTS script cannot be empty")
    if len(script) > 2000:
        raise IllyVoIPValidationError(
            "TTS script is too long; IllyVoIP accepts at most 2,000 characters"
        )
    return script


class IllyVoIPService:
    """Place real vishing calls and speak through IllyVoIP's native TTS.

    Args:
        settings: Optional settings override (tests).
        client: Optional ``httpx.AsyncClient`` double.  When supplied it is
            used as-is and is never closed by this service.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._base_url_error: str | None = None
        try:
            self._base_url = _normalize_base_url(
                self.settings.illyvoip_api_base_url
            )
        except IllyVoIPConfigurationError as exc:
            # Keep the service constructible so diagnostics can report the
            # exact configuration problem instead of returning a 500.
            self._base_url = (self.settings.illyvoip_api_base_url or "").strip().rstrip(
                "/"
            )
            self._base_url_error = str(exc)
        if (
            self.settings.is_production
            and self._base_url
            and not self._base_url.startswith("https://")
        ):
            self._base_url_error = (
                "ILLYVOIP_API_BASE_URL must use HTTPS in production"
            )

    # ------------------------------------------------------------------ #
    # Configuration and diagnostics
    # ------------------------------------------------------------------ #
    def configuration_status(self) -> dict[str, Any]:
        """Return non-secret readiness for the real vishing channel.

        The API key is never included.  The caller ID is a business identity,
        not a secret, and is returned so the operator can confirm the line.
        """
        missing = self.settings.illyvoip_missing_settings()
        if self._base_url_error:
            missing = [*missing, "ILLYVOIP_API_BASE_URL"]
        caller = _clean_optional(self.settings.illyvoip_caller_id)
        normalized_caller = re.sub(r"[\s\-()]", "", caller)
        caller_valid = bool(
            normalized_caller and CALLER_ID_RE.fullmatch(normalized_caller)
        )
        if caller and not caller_valid:
            missing = [*missing, "ILLYVOIP_CALLER_ID"]
        return {
            "provider": "illyvoip",
            "valid": not missing,
            "configured": self.settings.illyvoip_configured,
            "base_url": self._base_url,
            "sip_user_id": _clean_optional(self.settings.illyvoip_sip_user_id)
            or None,
            "caller_id": caller or None,
            "caller_id_valid": caller_valid,
            "missing": sorted(set(missing)),
            "warnings": self.settings.illyvoip_identity_warnings(),
            "tts_language": _clean_optional(self.settings.illyvoip_tts_language)
            or None,
            "tts_voice": _clean_optional(self.settings.illyvoip_tts_voice) or None,
            "record_calls": bool(self.settings.illyvoip_record_calls),
            "sandbox": bool(_clean_optional(self.settings.illyvoip_sandbox_scenario)),
        }

    def missing_settings(self) -> list[str]:
        """Return the environment variable names still required for a call."""
        return list(self.configuration_status()["missing"])

    async def voice_backend_status(self) -> dict[str, Any]:
        """Call ``GET /api/v1/voice/backend/status`` with the configured key."""
        self._require_api_key()
        async with self._client_context() as client:
            return await self._request(
                client, "GET", "/api/v1/voice/backend/status"
            )

    async def verify_configuration(self) -> dict[str, Any]:
        """Validate local settings and the live Voice API readiness endpoint.

        This never places a call.  It is safe to use as a preflight check.
        """
        status = self.configuration_status()
        if not status["valid"]:
            missing = ", ".join(status["missing"]) or "IllyVoIP configuration"
            return {
                **status,
                "api_reachable": False,
                "backend_status": None,
                "error": (
                    f"IllyVoIP is not configured; set {missing} in backend/.env"
                ),
                "hint": (
                    "Add ILLYVOIP_API_KEY to backend/.env, then restart the "
                    "API. ILLYVOIP_SIP_USER_ID and ILLYVOIP_CALLER_ID are "
                    "optional; without them the account defaults are used."
                ),
            }
        try:
            data = await self.voice_backend_status()
        except IllyVoIPError as exc:
            return {
                **status,
                "valid": False,
                "api_reachable": False,
                "backend_status": None,
                "error": str(exc),
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "hint": "Check the API key and the IllyVoIP service status.",
            }
        backend = str(data.get("backend_status") or "unknown").strip().lower()
        ready = backend in {"operational", "degraded"}
        return {
            **status,
            "valid": ready,
            "api_reachable": True,
            "backend_status": backend,
            "message": data.get("message"),
            "error": None
            if ready
            else (data.get("message") or f"Voice backend is {backend}"),
            "hint": None if ready else "IllyVoIP reports that the Voice API is unavailable.",
        }

    async def list_tts_languages(self, *, context: str = "voice_api") -> dict[str, Any]:
        """Return the provider's current TTS language catalog."""
        self._require_api_key()
        async with self._client_context() as client:
            return await self._request(
                client,
                "GET",
                "/api/v1/tts/languages",
                params={"context": context},
            )

    async def list_tts_voices(
        self,
        *,
        language: str | None = None,
        context: str = "voice_api",
    ) -> dict[str, Any]:
        """Return the provider's current TTS voice catalog for a language."""
        self._require_api_key()
        lang = _clean_optional(language or self.settings.illyvoip_tts_language)
        params: dict[str, Any] = {"context": context}
        if lang:
            params["language"] = lang
        async with self._client_context() as client:
            return await self._request(
                client,
                "GET",
                "/api/v1/tts/voices",
                params=params,
            )

    # ------------------------------------------------------------------ #
    # Public call-control operations
    # ------------------------------------------------------------------ #
    async def create_call(
        self,
        to_phone: str,
        *,
        from_phone: str | None = None,
        sip_user_id: str | None = None,
        timeout_seconds: int | None = None,
        record: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a real outbound call and return the provider response.

        The response's ``call_control_id`` is the handle for every later
        action.  A successful response only means the request was accepted;
        call :meth:`wait_for_answer` to establish that the destination
        actually answered.
        """
        self._require_configured()
        async with self._client_context() as client:
            return await self._create_call(
                client,
                to_phone,
                from_phone=from_phone,
                sip_user_id=sip_user_id,
                timeout_seconds=timeout_seconds,
                record=record,
                idempotency_key=idempotency_key,
            )

    async def get_call_status(self, call_control_id: str) -> dict[str, Any]:
        """Return the current provider state for one call."""
        self._require_configured()
        async with self._client_context() as client:
            return await self._get_status(client, call_control_id)

    async def wait_for_answer(
        self,
        call_control_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Poll until the call is answered or reaches a terminal state.

        Raises:
            IllyVoIPCallFailedError: The call ended before it was answered.
            IllyVoIPTimeoutError: The bounded answer deadline elapsed.
        """
        self._require_configured()
        async with self._client_context() as client:
            status, _observation = await self._wait_for_answer(
                client,
                call_control_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            return status

    async def speak(
        self,
        call_control_id: str,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        idempotency_key: str | None = None,
        pending_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Synthesise and play ``text`` into an active call.

        The request is retried with the same idempotency key while IllyVoIP
        reports ``voice_request_pending``.  A ``voice_content_review_required``
        response raises :class:`IllyVoIPContentReviewError`; it is never
        retried because the provider has already refused the text.
        """
        self._require_configured()
        async with self._client_context() as client:
            return await self._speak(
                client,
                call_control_id,
                text,
                language=language,
                voice=voice,
                idempotency_key=idempotency_key,
                pending_timeout_seconds=pending_timeout_seconds,
            )

    async def wait(self, call_control_id: str, seconds: int) -> dict[str, Any]:
        """Keep an active call open for ``seconds``.

        The service splits long playback waits into short chunks so each HTTP
        request stays inside the configured read timeout.
        """
        self._require_configured()
        async with self._client_context() as client:
            return await self._wait(client, call_control_id, seconds)

    async def hangup(
        self,
        call_control_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """End a live call.

        IllyVoIP treats a repeated hangup as idempotent and returns
        ``idempotent: true`` when the call was already confirmed ended.
        """
        self._require_configured()
        async with self._client_context() as client:
            return await self._hangup(
                client,
                call_control_id,
                idempotency_key=idempotency_key,
            )

    async def ring_only_call(
        self,
        to_phone: str,
        *,
        campaign_id: str | uuid.UUID | None = None,
        tracking_uuid: str | uuid.UUID | None = None,
        from_phone: str | None = None,
        sip_user_id: str | None = None,
        ring_timeout_seconds: float = 30.0,
        record: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ring one number and hang up the moment it starts ringing.

        No script is sent, so this spends no TTS credit.  The method hangs up
        at the first ringing observation and also cleans up an early answer or
        a timeout.  It exists to prove the voice path end to end (credentials,
        caller ID, SIP line, destination reachability) without running a
        vishing script.

        Returns:
            ``call_control_id``, ``rang``, ``ring_seconds`` and the terminal
            ``state``.

        Raises:
            IllyVoIPCallFailedError: The call ended before it ever rang, or it
                rang but the provider could not confirm that it was hung up.
        """
        self._require_configured()
        recipient = _normalize_recipient(to_phone)
        async with self._client_context() as client:
            created = await self._create_call(
                client,
                recipient,
                from_phone=from_phone,
                sip_user_id=sip_user_id,
                timeout_seconds=max(1, int(ring_timeout_seconds)),
                record=record,
                idempotency_key=idempotency_key,
            )
            call_id = _validate_call_control_id(created["call_control_id"])
            started = time.monotonic()
            deadline = started + ring_timeout_seconds
            last_status: dict[str, Any] = created
            rang_at: float | None = None
            while time.monotonic() < deadline:
                last_status = await self._get_status(client, call_id)
                if self._is_ringing(last_status):
                    rang_at = time.monotonic()
                    logger.info(
                        "illyvoip_ring_only_rang",
                        call_control_id=call_id,
                        seconds=round(rang_at - started, 2),
                    )
                    break
                if self._is_answered(last_status) or self._is_terminal(last_status):
                    break
                await asyncio.sleep(self.settings.illyvoip_poll_interval_seconds)

            hangup: dict[str, Any] | None = None
            hangup_error: IllyVoIPError | None = None
            # Cut immediately: a ring-only check must never be answered.  Also
            # clean up a timeout or an early answer so the provider cannot keep
            # the call (and its billing) alive after this method returns.
            if not self._is_terminal(last_status):
                try:
                    hangup = await self._hangup(client, call_id)
                except IllyVoIPError as exc:
                    hangup_error = exc
                    logger.warning(
                        "illyvoip_ring_only_hangup_failed",
                        call_control_id=call_id,
                        status_code=exc.status_code,
                        error_code=exc.error_code,
                    )
                    # A failed hangup can mean the carrier already ended the
                    # call.  Confirm before reporting a false failure.
                    try:
                        last_status = await self._get_status(client, call_id)
                    except IllyVoIPError:
                        pass
                    if self._is_terminal(last_status):
                        hangup_error = None
            if rang_at is None:
                reason = (
                    last_status.get("failure_reason")
                    or last_status.get("call_status")
                    or last_status.get("state")
                    or "no ringing observed"
                )
                raise IllyVoIPCallFailedError(
                    f"IllyVoIP call {call_id} never rang: {reason}",
                    error_code="call_failed",
                    fields={
                        "call_control_id": call_id,
                        "rang": False,
                        "status": last_status,
                        "hangup": hangup,
                        "hangup_error": str(hangup_error) if hangup_error else None,
                    },
                )
            if hangup_error is not None:
                # The handset did ring, but leaving the call active would risk
                # an answer and further charges.  Surface the call id so the
                # caller can retry the hangup explicitly.
                raise IllyVoIPCallFailedError(
                    f"IllyVoIP call {call_id} rang but could not be hung up: "
                    f"{hangup_error}",
                    status_code=hangup_error.status_code,
                    error_code="hangup_failed",
                    fields={
                        "call_control_id": call_id,
                        "rang": True,
                        "ring_seconds": round(rang_at - started, 2),
                        "status": last_status,
                        "hangup_error": str(hangup_error),
                    },
                )
            return {
                "call_control_id": call_id,
                "rang": True,
                "ring_seconds": round(rang_at - started, 2),
                "state": (hangup or {}).get("state")
                or (
                    last_status.get("state")
                    if self._is_terminal(last_status)
                    else None
                )
                or "hangup_requested",
                "call_status": (hangup or {}).get("call_status"),
                "hangup": hangup,
                "provider_status": last_status,
            }

    async def place_vishing_call(
        self,
        to_phone: str,
        script_text: str,
        *,
        campaign_id: str | uuid.UUID | None = None,
        tracking_uuid: str | uuid.UUID | None = None,
        language: str | None = None,
        voice: str | None = None,
        from_phone: str | None = None,
        sip_user_id: str | None = None,
        answer_timeout_seconds: float | None = None,
        record: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create, answer, speak, wait and hang up one real vishing call.

        The deterministic idempotency keys are derived from
        ``campaign_id`` + ``tracking_uuid`` when both are supplied.  Passing
        the same pair again after an ambiguous transport failure is safe: the
        provider replays the original create/speak/hangup result instead of
        placing a second call or charging the script twice.

        Returns:
            A JSON-serialisable dictionary with the provider call id, final
            state, TTS media/charge and hangup result.

        Raises:
            IllyVoIPConfigurationError: Missing credentials or caller ID.
            IllyVoIPValidationError: Invalid destination or script.
            IllyVoIPCallFailedError: Call ended before answer.
            IllyVoIPTimeoutError: Answer or TTS-pending deadline elapsed.
            IllyVoIPContentReviewError: Text was refused by content review.
            IllyVoIPAPIError: Provider rejected a control action.
            IllyVoIPTransportError: Network failure.
        """
        self._require_configured()
        recipient = _normalize_recipient(to_phone)
        script = _validate_script(script_text)
        if idempotency_key:
            base_key = re.sub(r"[^A-Za-z0-9_-]", "-", idempotency_key.strip())[
                :100
            ]
            if len(base_key) < 8:
                raise IllyVoIPValidationError(
                    "idempotency_key must be at least 8 characters"
                )
            create_key = f"{base_key}-create"
            speak_key = f"{base_key}-speak"
            hangup_key = f"{base_key}-hangup"
        else:
            create_key = self.build_idempotency_key(
                campaign_id, tracking_uuid, "create"
            )
            speak_key = self.build_idempotency_key(
                campaign_id, tracking_uuid, "speak"
            )
            hangup_key = self.build_idempotency_key(
                campaign_id, tracking_uuid, "hangup"
            )
        started = time.monotonic()
        call_id: str | None = None

        async with self._client_context() as client:
            try:
                created = await self._create_call(
                    client,
                    recipient,
                    from_phone=from_phone,
                    sip_user_id=sip_user_id,
                    record=record,
                    idempotency_key=create_key,
                )
                call_id = str(created["call_control_id"])
                answered, observation = await self._wait_for_answer(
                    client,
                    call_id,
                    timeout_seconds=answer_timeout_seconds,
                )
                spoken = await self._speak(
                    client,
                    call_id,
                    script,
                    language=language,
                    voice=voice,
                    idempotency_key=speak_key,
                )

                playback_seconds = self.estimate_speech_seconds(script)
                try:
                    await self._wait_for_playback(
                        client, call_id, playback_seconds
                    )
                except IllyVoIPAPIError as exc:
                    # The recipient may have hung up while the prompt played.
                    # A 404/409 here means there is nothing left to control;
                    # fetch the final status below instead of masking the call.
                    if exc.status_code not in {404, 409}:
                        raise
                    logger.info(
                        "illyvoip_playback_wait_call_ended",
                        call_control_id=call_id,
                        status_code=exc.status_code,
                    )
                except IllyVoIPTransportError as exc:
                    # The provider can hold ``/wait`` longer than the client read
                    # timeout, and a recipient hanging up fails the request.  The
                    # call has already been placed, answered and spoken, so this
                    # must never turn a completed call into an error response.
                    logger.warning(
                        "illyvoip_playback_wait_transport_error",
                        call_control_id=call_id,
                        error=str(exc)[:200],
                    )

                final = await self._get_status(client, call_id)
                hangup_result: dict[str, Any] | None = None
                if not self._is_terminal(final):
                    hangup_result = await self._hangup(
                        client, call_id, idempotency_key=hangup_key
                    )
                    try:
                        final = await self._get_status(client, call_id)
                    except IllyVoIPError as exc:
                        # The hangup response is authoritative enough if the
                        # final status read fails immediately afterwards.
                        logger.warning(
                            "illyvoip_final_status_after_hangup_failed",
                            call_control_id=call_id,
                            status_code=exc.status_code,
                            error_code=exc.error_code,
                        )
                        if str(hangup_result.get("status")).lower() == "success":
                            final = {
                                **final,
                                "state": "completed",
                                "call_status": "completed",
                                "terminal": True,
                            }

                result = IllyVoIPCallResult(
                    call_control_id=call_id,
                    state=str(final.get("state") or ""),
                    call_status=str(final.get("call_status") or ""),
                    answered_at=answered.get("answered_at"),
                    ended_at=final.get("ended_at"),
                    failure_reason=final.get("failure_reason"),
                    tts_media=spoken.get("media"),
                    tts_charge=spoken.get("tts_charge")
                    if isinstance(spoken.get("tts_charge"), dict)
                    else None,
                    hangup=hangup_result,
                    duration_seconds=round(time.monotonic() - started, 3),
                    rang=observation.rang,
                    answer_delay_seconds=observation.answer_delay_seconds,
                    answer_suspect_auto=observation.suspect_auto_answer,
                )
                logger.info(
                    "illyvoip_vishing_call_completed",
                    call_control_id=call_id,
                    to=mask_phone(recipient),
                    state=result.state,
                    call_status=result.call_status,
                    duration_seconds=result.duration_seconds,
                    rang=result.rang,
                    answer_delay_seconds=result.answer_delay_seconds,
                    answer_suspect_auto=result.answer_suspect_auto,
                )
                if result.answer_suspect_auto:
                    # Never let an automatic answer masquerade as a human one.
                    logger.warning(
                        "illyvoip_answer_not_verified_human",
                        call_control_id=call_id,
                        to=mask_phone(recipient),
                        answer_delay_seconds=result.answer_delay_seconds,
                    )
                return result.as_dict()
            except Exception as exc:
                if call_id:
                    # Attach the provider handle so the API can persist a
                    # failed attempt against the correct tracking row.
                    if isinstance(exc, IllyVoIPError):
                        exc.fields.setdefault("call_control_id", call_id)
                    await self._safe_hangup(
                        client, call_id, idempotency_key=hangup_key
                    )
                raise

    # ------------------------------------------------------------------ #
    # Idempotency
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_idempotency_key(
        campaign_id: str | uuid.UUID | None,
        tracking_uuid: str | uuid.UUID | None,
        action: str,
    ) -> str:
        """Build a deterministic, non-PII idempotency key.

        The provider requires 8-128 characters.  When both identifiers are
        present the key is stable across process restarts, which is what makes
        retrying an ambiguous request safe.  Without both identifiers a random
        key is returned; callers that retry must reuse it explicitly.
        """
        safe_action = re.sub(r"[^a-z0-9_-]", "-", (action or "request").lower())[
            :24
        ] or "request"
        if campaign_id and tracking_uuid:
            raw = (
                f"humint-shield:vishing:{campaign_id}:{tracking_uuid}:"
                f"{safe_action}"
            )
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]
            return f"vishing-{digest}"
        return f"vishing-{uuid.uuid4().hex}"

    # ------------------------------------------------------------------ #
    # Playback timing
    # ------------------------------------------------------------------ #
    def estimate_speech_seconds(self, text: str) -> int:
        """Estimate how long ``text`` needs to play before hangup.

        IllyVoIP's ``/speak`` response does not expose a playback-completion
        flag (``wait_for_playback_completion`` is not in the documented request
        schema), so the service keeps the call open for a conservative,
        configurable estimate and then hangs up.
        """
        characters = len((text or "").strip())
        rate = max(1.0, float(self.settings.illyvoip_tts_chars_per_second or 12.0))
        padding = max(0.0, float(self.settings.illyvoip_tts_padding_seconds or 0.0))
        estimate = math.ceil(characters / rate + padding)
        maximum = max(1, int(self.settings.illyvoip_max_speech_wait_seconds or 180))
        return max(1, min(estimate, maximum))

    # ------------------------------------------------------------------ #
    # Internal operations (share one HTTP client)
    # ------------------------------------------------------------------ #
    async def _create_call(
        self,
        client: httpx.AsyncClient,
        to_phone: str,
        *,
        from_phone: str | None = None,
        sip_user_id: str | None = None,
        timeout_seconds: int | None = None,
        record: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        recipient = _normalize_recipient(to_phone)
        # ``sip_user_id`` and ``from`` are optional in the provider contract:
        # omitting them makes IllyVoIP use the account's main SIP identity and
        # default caller ID.  Send them only when they are configured.
        caller_value = _clean_optional(
            from_phone or self.settings.illyvoip_caller_id
        )
        sip = _clean_optional(sip_user_id or self.settings.illyvoip_sip_user_id)
        body: dict[str, Any] = {"to": recipient}
        if caller_value:
            body["from"] = _normalize_caller_id(caller_value)
        if sip:
            body["sip_user_id"] = sip
        body["record"] = bool(
            self.settings.illyvoip_record_calls if record is None else record
        )
        if timeout_seconds is not None:
            body["timeout_seconds"] = max(1, int(timeout_seconds))
        normalized_caller = str(body.get("from") or "")
        if normalized_caller and normalized_caller.lstrip("+") == recipient.lstrip("+"):
            # Presenting the callee's own number is rejected or silently dropped
            # by most carriers (anti-spoofing): the provider can show "ringing"
            # while the handset never alerts.  Never let that look like delivery.
            logger.warning(
                "illyvoip_caller_id_equals_destination",
                to=mask_phone(recipient),
            )
        key = idempotency_key or self.build_idempotency_key(
            None, None, "create"
        )
        data = await self._request(
            client,
            "POST",
            "/api/v1/voice/call-control/calls",
            json_body=body,
            idempotency_key=key,
        )
        call_id = data.get("call_control_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise IllyVoIPAPIError(
                "IllyVoIP create-call response did not contain a call_control_id"
            )
        # In dynamic caller-ID mode the provider only accepts a number the account
        # owns or has verified.  When the presented number is not eligible it is
        # dropped silently (``from`` comes back empty) and the call dies before
        # ringing: surface that instead of a generic transport failure.
        if caller_value and not str(data.get("from") or "").strip():
            logger.warning(
                "illyvoip_caller_id_not_presented",
                requested_from=_normalize_caller_id(caller_value),
                to=mask_phone(recipient),
            )
        if str(data.get("state") or "").strip().lower() == "failed":
            raise IllyVoIPCallFailedError(
                "IllyVoIP rejected the outbound call",
                status_code=200,
                error_code="call_create_failed",
            )
        logger.info(
            "illyvoip_call_created",
            call_control_id=call_id,
            to=mask_phone(recipient),
            sip_user_id=sip,
            reconciliation_pending=bool(data.get("reconciliation_pending")),
        )
        return data

    async def _get_status(
        self, client: httpx.AsyncClient, call_control_id: str
    ) -> dict[str, Any]:
        call_id = _validate_call_control_id(call_control_id)
        data = await self._request(
            client,
            "POST",
            "/api/v1/voice/call-control/status",
            json_body={"call_control_id": call_id},
        )
        if str(data.get("status") or "").lower() != "success":
            raise IllyVoIPAPIError(
                "IllyVoIP status response was not successful",
                status_code=200,
            )
        return data

    async def _wait_for_answer(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> tuple[dict[str, Any], AnswerObservation]:
        call_id = _validate_call_control_id(call_control_id)
        min_human_delay = max(
            0.0, float(self.settings.illyvoip_min_answer_delay_seconds or 0.0)
        )
        timeout = float(
            self.settings.illyvoip_answer_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout <= 0:
            raise IllyVoIPValidationError("answer timeout must be greater than zero")
        interval = float(
            self.settings.illyvoip_poll_interval_seconds
            if poll_interval_seconds is None
            else poll_interval_seconds
        )
        interval = max(0.05, interval)
        deadline = time.monotonic() + timeout
        last_status: dict[str, Any] | None = None
        ring_started: float | None = None

        while True:
            try:
                last_status = await self._get_status(client, call_id)
            except IllyVoIPAPIError as exc:
                # A freshly created call can briefly return 404 while the
                # provider reconciles it.  Retry only while the deadline holds;
                # a 409 is a real state conflict and must surface immediately.
                if exc.status_code == 404 and time.monotonic() < deadline:
                    await asyncio.sleep(
                        min(interval, max(0.0, deadline - time.monotonic()))
                    )
                    continue
                raise

            if self._is_ringing(last_status):
                if ring_started is None:
                    ring_started = time.monotonic()
                    logger.info(
                        "illyvoip_call_ringing",
                        call_control_id=call_id,
                        state=last_status.get("state"),
                        call_status=last_status.get("call_status"),
                    )

            if self._is_answered(last_status):
                answered_now = time.monotonic()
                delay = (
                    round(answered_now - ring_started, 2)
                    if ring_started is not None
                    else None
                )
                observation = AnswerObservation(
                    rang=ring_started is not None,
                    observed_ringing=ring_started is not None,
                    ring_seconds=delay,
                    answer_delay_seconds=delay,
                    # No ringing at all, or an answer faster than a person could
                    # plausibly pick up: treat it as unattended (voicemail, IVR or
                    # a carrier announcement) instead of an acknowledgement.
                    suspect_auto_answer=(
                        ring_started is None
                        or (delay is not None and delay < min_human_delay)
                    ),
                )
                logger.info(
                    "illyvoip_call_answered",
                    call_control_id=call_id,
                    state=last_status.get("state"),
                    call_status=last_status.get("call_status"),
                    rang=observation.rang,
                    answer_delay_seconds=delay,
                    suspect_auto_answer=observation.suspect_auto_answer,
                )
                return last_status, observation

            if self._is_terminal(last_status):
                reason = (
                    last_status.get("failure_reason")
                    or last_status.get("call_status")
                    or last_status.get("state")
                    or "call ended before answer"
                )
                raise IllyVoIPCallFailedError(
                    f"IllyVoIP call {call_id} ended before answer: {reason}",
                    error_code="call_not_answered",
                    fields={
                        "status": last_status,
                        "call_control_id": call_id,
                        "rang": ring_started is not None,
                        "ring_seconds": (
                            round(time.monotonic() - ring_started, 2)
                            if ring_started is not None
                            else None
                        ),
                    },
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IllyVoIPTimeoutError(
                    f"IllyVoIP call {call_id} was not answered within "
                    f"{timeout:.0f}s"
                )
            await asyncio.sleep(min(interval, remaining))

    async def _speak(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        idempotency_key: str | None = None,
        pending_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        call_id = _validate_call_control_id(call_control_id)
        script = _validate_script(text)
        body: dict[str, Any] = {"call_control_id": call_id, "text": script}
        explicit_language = _clean_optional(language)
        default_language = _clean_optional(self.settings.illyvoip_tts_language)
        lang = explicit_language or detect_tts_language(
            script,
            default=default_language,
            arabic=_clean_optional(self.settings.illyvoip_tts_arabic_language),
        )
        if lang:
            body["language"] = lang
        voice_name = _clean_optional(voice or self.settings.illyvoip_tts_voice)
        if voice_name:
            body["voice"] = voice_name

        key = idempotency_key or self.build_idempotency_key(None, None, "speak")
        timeout = float(
            self.settings.illyvoip_tts_pending_timeout_seconds
            if pending_timeout_seconds is None
            else pending_timeout_seconds
        )
        deadline = time.monotonic() + max(0.0, timeout)
        interval = max(0.05, float(self.settings.illyvoip_poll_interval_seconds))

        while True:
            try:
                data = await self._request(
                    client,
                    "POST",
                    "/api/v1/voice/call-control/speak",
                    json_body=body,
                    idempotency_key=key,
                )
            except IllyVoIPAPIError as exc:
                if (
                    exc.error_code == "voice_request_pending"
                    and exc.status_code in {409, 503}
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IllyVoIPTimeoutError(
                            "IllyVoIP TTS request is still pending after "
                            f"{timeout:.0f}s; reuse the same idempotency key "
                            "before starting a new request"
                        ) from exc
                    delay = max(interval, float(exc.retry_after or 0.0))
                    await asyncio.sleep(min(delay, remaining))
                    continue
                raise

            if str(data.get("status") or "").lower() != "success":
                raise IllyVoIPAPIError(
                    "IllyVoIP speak response was not successful",
                    status_code=200,
                )
            logger.info(
                "illyvoip_speak_started",
                call_control_id=call_id,
                characters=len(script),
                language=lang or None,
                voice=voice_name or None,
            )
            return data

    async def _wait(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        seconds: int,
    ) -> dict[str, Any]:
        call_id = _validate_call_control_id(call_control_id)
        duration = max(0, int(seconds))
        if duration == 0:
            return {
                "status": "success",
                "call_control_id": call_id,
                "seconds": 0,
            }
        data = await self._request(
            client,
            "POST",
            "/api/v1/voice/call-control/wait",
            json_body={"call_control_id": call_id, "seconds": duration},
        )
        if str(data.get("status") or "").lower() != "success":
            raise IllyVoIPAPIError(
                "IllyVoIP wait response was not successful",
                status_code=200,
            )
        return data

    async def _wait_for_playback(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        total_seconds: int,
    ) -> None:
        """Wait in bounded chunks so one HTTP request cannot time out.

        A ``/wait`` timeout only loses the response, not the call: IllyVoIP has
        already been asked to hold the line for that chunk.  Instead of failing
        the whole call, the timeout is logged and the call state is checked so
        an ended call is detected.
        """
        remaining = max(0, int(total_seconds))
        chunk = max(1, int(self.settings.illyvoip_wait_chunk_seconds or 15))
        while remaining > 0:
            duration = min(remaining, chunk)
            try:
                await self._wait(client, call_control_id, duration)
            except IllyVoIPTransportError as exc:
                logger.warning(
                    "illyvoip_playback_wait_timeout",
                    call_control_id=call_control_id,
                    seconds=duration,
                    error=str(exc)[:200],
                )
            except IllyVoIPAPIError as exc:
                if exc.status_code in {404, 409}:
                    return
                raise
            remaining -= duration
            if remaining <= 0:
                return
            try:
                status = await self._get_status(client, call_control_id)
            except IllyVoIPAPIError as exc:
                if exc.status_code in {404, 409}:
                    return
                raise
            except IllyVoIPTransportError as exc:
                logger.warning(
                    "illyvoip_playback_status_timeout",
                    call_control_id=call_control_id,
                    error=str(exc)[:200],
                )
                return
            if self._is_terminal(status):
                return

    async def _hangup(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        call_id = _validate_call_control_id(call_control_id)
        # IllyVoIP intermittently answers hangup with 503 "Unable to terminate
        # the call right now"; retrying briefly is the documented way to stop a
        # call that is still ringing, so never give up after a single attempt.
        data: dict[str, Any] = {}
        last_error: IllyVoIPAPIError | None = None
        for attempt in range(3):
            key = idempotency_key if attempt == 0 else None
            key = key or self.build_idempotency_key(None, None, "hangup")
            try:
                data = await self._request(
                    client,
                    "POST",
                    "/api/v1/voice/call-control/hangup",
                    json_body={"call_control_id": call_id},
                    idempotency_key=key,
                )
                last_error = None
                break
            except IllyVoIPAPIError as exc:
                if (exc.status_code or 0) < 500:
                    raise
                last_error = exc
                logger.warning(
                    "illyvoip_call_hangup_retry",
                    call_control_id=call_id,
                    status_code=exc.status_code,
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(0.4 * (attempt + 1))
        if last_error is not None:
            raise last_error
        if str(data.get("status") or "").lower() != "success":
            raise IllyVoIPAPIError(
                "IllyVoIP hangup response was not successful",
                status_code=200,
            )
        logger.info(
            "illyvoip_call_hangup",
            call_control_id=call_id,
            idempotent=bool(data.get("idempotent")),
        )
        return data

    async def _safe_hangup(
        self,
        client: httpx.AsyncClient,
        call_control_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        """Best-effort cleanup; never mask the original failure."""
        try:
            await self._hangup(
                client,
                call_control_id,
                idempotency_key=idempotency_key,
            )
        except IllyVoIPError as exc:
            logger.warning(
                "illyvoip_cleanup_hangup_failed",
                call_control_id=call_control_id,
                status_code=exc.status_code,
                error_code=exc.error_code,
            )

    # ------------------------------------------------------------------ #
    # HTTP plumbing
    # ------------------------------------------------------------------ #
    def _require_api_key(self) -> None:
        if not self.settings.illyvoip_api_key_configured:
            raise IllyVoIPConfigurationError(
                "IllyVoIP is not configured; set ILLYVOIP_API_KEY in backend/.env"
            )

    def _require_configured(self) -> None:
        missing = self.missing_settings()
        if missing:
            raise IllyVoIPConfigurationError(
                "IllyVoIP is not configured; set "
                + ", ".join(missing)
                + " in backend/.env"
            )

    @asynccontextmanager
    async def _client_context(self) -> AsyncIterator[httpx.AsyncClient]:
        """Yield the injected client or a short-lived production client."""
        if self._client is not None:
            yield self._client
            return
        timeout = float(self.settings.illyvoip_timeout_seconds or 20.0)
        # ``/wait`` blocks for the requested chunk, and the provider can take
        # noticeably longer than the chunk to answer.  Give the read far more
        # headroom than the chunk itself so a healthy call is not reported as a
        # transport failure.
        read_timeout = max(
            timeout,
            float(self.settings.illyvoip_wait_chunk_seconds or 15) * 2 + 10.0,
        )
        http_timeout = httpx.Timeout(
            timeout,
            connect=min(10.0, timeout),
            read=read_timeout,
            write=timeout,
            pool=5.0,
        )
        async with httpx.AsyncClient(
            timeout=http_timeout,
            follow_redirects=False,
        ) as client:
            yield client

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "X-Api-Key": (self.settings.illyvoip_api_key or "").strip(),
            "Accept": "application/json",
        }
        if idempotency_key:
            if not 8 <= len(idempotency_key) <= 128:
                raise IllyVoIPValidationError(
                    "Idempotency-Key must be between 8 and 128 characters"
                )
            headers["Idempotency-Key"] = idempotency_key
        scenario = _clean_optional(self.settings.illyvoip_sandbox_scenario)
        if scenario:
            headers["X-Illyvoip-Sandbox-Scenario"] = scenario
        return headers

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = self._headers(idempotency_key=idempotency_key)
        try:
            response = await client.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise IllyVoIPTransportError(
                f"IllyVoIP {method} {path} timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise IllyVoIPTransportError(
                f"IllyVoIP {method} {path} transport error: {exc}"
            ) from exc
        return self._decode(response, method=method, path=path)

    @staticmethod
    def _decode(
        response: httpx.Response,
        *,
        method: str,
        path: str,
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if not isinstance(payload, dict):
            raise IllyVoIPAPIError(
                f"IllyVoIP {method} {path} returned a non-JSON response "
                f"(HTTP {response.status_code})",
                status_code=response.status_code,
                retryable=response.status_code in _RETRYABLE_STATUS_CODES,
            )

        if response.status_code >= 400 or str(payload.get("status")).lower() == "error":
            IllyVoIPService._raise_api_error(response, payload)
        return payload

    @staticmethod
    def _raise_api_error(
        response: httpx.Response, payload: dict[str, Any]
    ) -> None:
        status_code = response.status_code
        message = str(
            payload.get("message")
            or payload.get("detail")
            or f"IllyVoIP returned HTTP {status_code}"
        )
        error_code = payload.get("error_code") or payload.get("code")
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        retryable = status_code in _RETRYABLE_STATUS_CODES or (
            status_code == 409 and error_code == "voice_request_pending"
        )

        if status_code == 403 and error_code == "voice_content_review_required":
            reference = fields.get("review_reference")
            raise IllyVoIPContentReviewError(
                message,
                review_reference=str(reference) if reference else None,
                status_code=status_code,
                fields=fields,
            )

        raise IllyVoIPAPIError(
            message,
            status_code=status_code,
            error_code=str(error_code) if error_code else None,
            fields=fields,
            retryable=retryable,
            retry_after=retry_after,
        )

    @staticmethod
    def _is_answered(status: dict[str, Any]) -> bool:
        if status.get("answered_at"):
            return True
        state = str(status.get("state") or "").strip().lower()
        call_status = str(status.get("call_status") or "").strip().lower()
        return state in _ANSWERED_STATES or call_status in _ANSWERED_STATES

    @staticmethod
    def _is_ringing(status: dict[str, Any]) -> bool:
        """Return ``True`` while the destination is alerting the recipient."""
        state = str(status.get("state") or "").strip().lower()
        call_status = str(status.get("call_status") or "").strip().lower()
        return state in _RINGING_STATES or call_status in _RINGING_STATES

    @staticmethod
    def _is_terminal(status: dict[str, Any]) -> bool:
        if status.get("terminal") is True:
            return True
        state = str(status.get("state") or "").strip().lower()
        call_status = str(status.get("call_status") or "").strip().lower()
        return state in _TERMINAL_STATES or call_status in _TERMINAL_STATES


__all__ = [
    "AnswerObservation",
    "CALLER_ID_RE",
    "MIN_PLAUSIBLE_HUMAN_ANSWER_SECONDS",
    "E164_RE",
    "IllyVoIPAPIError",
    "IllyVoIPCallFailedError",
    "IllyVoIPCallResult",
    "IllyVoIPConfigurationError",
    "IllyVoIPContentReviewError",
    "IllyVoIPError",
    "IllyVoIPService",
    "IllyVoIPTimeoutError",
    "IllyVoIPTransportError",
    "IllyVoIPValidationError",
    "is_e164_phone",
    "mask_phone",
]
