"""Real IllyVoIP Voice API integration.

Every HTTP interaction in this module uses ``httpx.MockTransport``.  No test
places a real call, spends real credit, or requires a real API key.  The tests
assert the documented request shape (``X-Api-Key``, ``Idempotency-Key``,
call-control payloads) and the production error paths.
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.config import Settings
from app.services.illyvoip_service import (
    IllyVoIPAPIError,
    IllyVoIPCallFailedError,
    IllyVoIPConfigurationError,
    detect_tts_language,
    IllyVoIPContentReviewError,
    IllyVoIPService,
    IllyVoIPTimeoutError,
    IllyVoIPValidationError,
    is_e164_phone,
)


def _settings(**overrides: object) -> Settings:
    """Return deterministic settings with a complete fake IllyVoIP setup."""
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "illyvoip_api_key": "test-illyvoip-key",
        "illyvoip_api_base_url": "https://api.illyvoip.test",
        "illyvoip_sip_user_id": "1051",
        "illyvoip_caller_id": "+15550001111",
        "illyvoip_timeout_seconds": 2.0,
        "illyvoip_answer_timeout_seconds": 0.3,
        "illyvoip_min_answer_delay_seconds": 0.0,
        "illyvoip_poll_interval_seconds": 0.01,
        "illyvoip_tts_language": "en-US",
        "illyvoip_tts_voice": "illyvoip-emma",
        "illyvoip_tts_arabic_language": "ar-AR",
        "illyvoip_tts_chars_per_second": 1000.0,
        "illyvoip_tts_padding_seconds": 0.0,
        "illyvoip_tts_pending_timeout_seconds": 0.3,
        "illyvoip_max_speech_wait_seconds": 2,
        "illyvoip_wait_chunk_seconds": 1,
        "illyvoip_record_calls": False,
        "illyvoip_sandbox_scenario": "",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _client(handler) -> httpx.AsyncClient:
    """Build an async client backed by an in-memory transport."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def _call_status(
    *,
    state: str = "ringing",
    call_status: str = "ringing",
    terminal: bool = False,
    answered_at: str | None = None,
    failure_reason: str | None = None,
) -> dict:
    return {
        "status": "success",
        "call_control_id": "vapi_test",
        "state": state,
        "call_status": call_status,
        "terminal": terminal,
        "to": "+966500000000",
        "from": "15550001111",
        "created_at": "2026-11-12 12:00:00+00:00",
        "answered_at": answered_at,
        "ended_at": None,
        "failure_reason": failure_reason,
    }


@pytest.mark.asyncio
async def test_place_vishing_call_success_uses_real_control_flow() -> None:
    """The happy path creates, answers, speaks, waits and hangs up."""
    requests: list[httpx.Request] = []
    status_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/voice/call-control/calls":
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "sip_user_id": "1051",
                    "to": "+966500000000",
                    "state": "accepted",
                }
            )
        if path == "/api/v1/voice/call-control/status":
            status_count["value"] += 1
            if status_count["value"] == 1:
                return _json(_call_status())
            return _json(
                _call_status(
                    state="active",
                    call_status="active",
                    answered_at="2026-11-12 12:00:05+00:00",
                )
            )
        if path == "/api/v1/voice/call-control/speak":
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "media": "vcm2.test-media",
                    "tts_charge": {
                        "transaction_id": "TX-1234567890AB",
                        "product": "voice_api_tts",
                        "characters": 21,
                        "rate_per_char_eur": 0.00005,
                        "amount_eur": 0.00105,
                    },
                }
            )
        if path == "/api/v1/voice/call-control/wait":
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "seconds": 1,
                }
            )
        if path == "/api/v1/voice/call-control/hangup":
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "message": "Call terminated.",
                    "terminated_channels": 1,
                }
            )
        return _json({"status": "error", "message": "unexpected path"}, 500)

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.place_vishing_call(
            "+966500000000",
            "Hello from the security team.",
            campaign_id=uuid.uuid4(),
            tracking_uuid=uuid.uuid4(),
        )
    finally:
        await client.aclose()

    assert result["call_control_id"] == "vapi_test"
    assert result["state"] == "active"
    assert result["call_status"] == "active"
    assert result["tts_media"] == "vcm2.test-media"
    assert result["tts_charge"]["product"] == "voice_api_tts"
    assert result["hangup"]["terminated_channels"] == 1

    paths = [request.url.path for request in requests]
    assert paths[0].endswith("/calls")
    assert paths[1].endswith("/status")
    assert paths[2].endswith("/status")
    assert paths[3].endswith("/speak")
    assert "/wait" in "".join(paths)
    assert paths[-2].endswith("/hangup")
    assert paths[-1].endswith("/status")

    create_body = json.loads(requests[0].content)
    assert create_body == {
        "to": "+966500000000",
        "from": "15550001111",
        "sip_user_id": "1051",
        "record": False,
    }
    assert requests[0].headers["X-Api-Key"] == "test-illyvoip-key"
    create_key = requests[0].headers["Idempotency-Key"]
    speak_key = requests[3].headers["Idempotency-Key"]
    hangup_key = requests[-2].headers["Idempotency-Key"]
    assert create_key.startswith("vishing-")
    assert speak_key.startswith("vishing-")
    assert hangup_key.startswith("vishing-")
    assert len({create_key, speak_key, hangup_key}) == 3

    speak_body = json.loads(requests[3].content)
    assert speak_body["text"] == "Hello from the security team."
    assert speak_body["language"] == "en-US"
    assert speak_body["voice"] == "illyvoip-emma"
    # The documented schema forbids extra properties; this flag is not sent.
    assert "wait_for_playback_completion" not in speak_body


@pytest.mark.asyncio
async def test_missing_configuration_fails_before_http() -> None:
    """A real call must never be attempted with placeholder credentials."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _json({"status": "success"})

    client = _client(handler)
    try:
        service = IllyVoIPService(
            settings=_settings(
                illyvoip_api_key="",
                illyvoip_sip_user_id="",
                illyvoip_caller_id="",
            ),
            client=client,
        )
        status = service.configuration_status()
        assert status["valid"] is False
        assert set(status["missing"]) == {"ILLYVOIP_API_KEY"}
        assert set(status["warnings"]) == {
            "ILLYVOIP_SIP_USER_ID",
            "ILLYVOIP_CALLER_ID",
        }
        with pytest.raises(IllyVoIPConfigurationError):
            await service.place_vishing_call("+966500000000", "Hello")
    finally:
        await client.aclose()
    assert calls == []


@pytest.mark.asyncio
async def test_optional_identity_is_omitted_so_account_defaults_apply() -> None:
    """``sip_user_id`` and ``from`` are optional in the provider contract.

    With only the API key configured the create body must omit both keys and
    let IllyVoIP use the account's main SIP identity and default caller ID.
    """
    requests: list[httpx.Request] = []
    status_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/voice/call-control/calls":
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "to": "+966500000000",
                    "state": "accepted",
                }
            )
        if path == "/api/v1/voice/call-control/status":
            status_count["value"] += 1
            if status_count["value"] == 1:
                return _json(_call_status())
            return _json(
                _call_status(
                    state="active",
                    call_status="active",
                    answered_at="2026-11-12 12:00:05+00:00",
                )
            )
        if path == "/api/v1/voice/call-control/speak":
            return _json({"status": "success", "media": "vcm2.test-media"})
        if path == "/api/v1/voice/call-control/wait":
            return _json({"status": "success", "seconds": 1})
        if path == "/api/v1/voice/call-control/hangup":
            return _json({"status": "success", "terminated_channels": 1})
        return _json({"status": "error", "message": "unexpected path"}, 500)

    client = _client(handler)
    try:
        service = IllyVoIPService(
            settings=_settings(
                illyvoip_sip_user_id="",
                illyvoip_caller_id="",
            ),
            client=client,
        )
        status = service.configuration_status()
        assert status["valid"] is True
        assert status["missing"] == []
        assert status["warnings"] == [
            "ILLYVOIP_SIP_USER_ID",
            "ILLYVOIP_CALLER_ID",
        ]
        await service.place_vishing_call("+966500000000", "Hello")
    finally:
        await client.aclose()

    create_body = json.loads(requests[0].content)
    assert create_body == {"to": "+966500000000", "record": False}


@pytest.mark.asyncio
async def test_invalid_recipient_and_script_are_rejected_locally() -> None:
    service = IllyVoIPService(settings=_settings(), client=_client(lambda _: _json({})))
    try:
        with pytest.raises(IllyVoIPValidationError):
            await service.place_vishing_call("0500000000", "Hello")
        with pytest.raises(IllyVoIPValidationError):
            await service.place_vishing_call("+966500000000", "   ")
        with pytest.raises(IllyVoIPValidationError):
            await service.place_vishing_call("+966500000000", "x" * 2001)
        assert is_e164_phone("+966500000000") is True
        assert is_e164_phone("0500000000") is False
    finally:
        await service._client.aclose()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_unanswered_call_times_out_and_is_hung_up() -> None:
    """The bounded answer deadline must not leave a live call behind."""
    hangup_calls = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "sip_user_id": "1051",
                    "to": "+966500000000",
                    "state": "accepted",
                }
            )
        if path.endswith("/status"):
            return _json(_call_status())
        if path.endswith("/hangup"):
            hangup_calls["value"] += 1
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "message": "Call terminated.",
                    "terminated_channels": 1,
                }
            )
        return _json({"status": "error", "message": "unexpected path"}, 500)

    client = _client(handler)
    try:
        service = IllyVoIPService(
            settings=_settings(illyvoip_answer_timeout_seconds=0.05),
            client=client,
        )
        with pytest.raises(IllyVoIPTimeoutError):
            await service.place_vishing_call("+966500000000", "Hello")
    finally:
        await client.aclose()
    assert hangup_calls["value"] == 1


@pytest.mark.asyncio
async def test_terminal_call_before_answer_raises_call_failed() -> None:
    speak_calls = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "sip_user_id": "1051",
                    "to": "+966500000000",
                    "state": "accepted",
                }
            )
        if path.endswith("/status"):
            return _json(
                _call_status(
                    state="failed",
                    call_status="busy",
                    terminal=True,
                    failure_reason="The destination is busy.",
                )
            )
        if path.endswith("/speak"):
            speak_calls["value"] += 1
            return _json({"status": "success"})
        if path.endswith("/hangup"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "message": "Call terminated.",
                    "terminated_channels": 1,
                }
            )
        return _json({"status": "error", "message": "unexpected path"}, 500)

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPCallFailedError) as excinfo:
            await service.place_vishing_call("+966500000000", "Hello")
    finally:
        await client.aclose()
    assert "busy" in str(excinfo.value).lower()
    assert speak_calls["value"] == 0


@pytest.mark.asyncio
async def test_speak_401_is_a_typed_non_retryable_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {"status": "error", "message": "The API key is invalid."},
            status_code=401,
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPAPIError) as excinfo:
            await service.speak("vapi_test", "Hello")
    finally:
        await client.aclose()
    assert excinfo.value.status_code == 401
    assert excinfo.value.retryable is False


@pytest.mark.asyncio
async def test_content_review_refusal_is_exposed_with_reference() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "status": "error",
                "message": "This text needs a communication review.",
                "error_code": "voice_content_review_required",
                "fields": {"review_reference": "RV-123"},
            },
            status_code=403,
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPContentReviewError) as excinfo:
            await service.speak("vapi_test", "Hello")
    finally:
        await client.aclose()
    assert excinfo.value.review_reference == "RV-123"
    assert excinfo.value.error_code == "voice_content_review_required"


@pytest.mark.asyncio
async def test_voice_request_pending_retries_with_same_key() -> None:
    keys: list[str] = []
    attempts = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/speak"):
            keys.append(request.headers["Idempotency-Key"])
            attempts["value"] += 1
            if attempts["value"] == 1:
                return _json(
                    {
                        "status": "error",
                        "message": "The previous request is still pending.",
                        "error_code": "voice_request_pending",
                    },
                    status_code=503,
                )
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "media": "vcm2.test-media",
                    "tts_charge": None,
                }
            )
        return _json({"status": "error", "message": "unexpected path"}, 500)

    client = _client(handler)
    try:
        service = IllyVoIPService(
            settings=_settings(illyvoip_tts_pending_timeout_seconds=0.5),
            client=client,
        )
        result = await service.speak("vapi_test", "Hello")
    finally:
        await client.aclose()
    assert result["media"] == "vcm2.test-media"
    assert attempts["value"] == 2
    assert keys[0] == keys[1]


@pytest.mark.asyncio
async def test_voice_request_closed_is_not_retried() -> None:
    attempts = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["value"] += 1
        return _json(
            {
                "status": "error",
                "message": "The request is closed.",
                "error_code": "voice_request_closed",
            },
            status_code=409,
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPAPIError) as excinfo:
            await service.speak("vapi_test", "Hello")
    finally:
        await client.aclose()
    assert excinfo.value.error_code == "voice_request_closed"
    assert attempts["value"] == 1


@pytest.mark.asyncio
async def test_verify_configuration_calls_backend_status() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json(
            {
                "status": "success",
                "backend_status": "operational",
                "message": "Voice backend is operational.",
            }
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.verify_configuration()
    finally:
        await client.aclose()
    assert result["valid"] is True
    assert result["api_reachable"] is True
    assert result["backend_status"] == "operational"
    assert seen[0].url.path == "/api/v1/voice/backend/status"
    assert seen[0].headers["X-Api-Key"] == "test-illyvoip-key"


@pytest.mark.asyncio
async def test_verify_configuration_reports_401_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {"status": "error", "message": "Invalid API key."},
            status_code=401,
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.verify_configuration()
    finally:
        await client.aclose()
    assert result["valid"] is False
    assert result["api_reachable"] is False
    assert result["status_code"] == 401
    assert "test-illyvoip-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_tts_catalog_uses_voice_api_context() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/languages"):
            return _json(
                {
                    "status": "success",
                    "context": "voice_api",
                    "default_language": "en-US",
                    "languages": [{"language": "en-US", "label": "English (US)"}],
                }
            )
        return _json(
            {
                "status": "success",
                "context": "voice_api",
                "language": "en-US",
                "default_voice": "illyvoip-emma",
                "voices": [
                    {
                        "voice": "illyvoip-emma",
                        "label": "Emma",
                        "language": "en-US",
                    }
                ],
            }
        )

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        languages = await service.list_tts_languages()
        voices = await service.list_tts_voices(language="en-US")
    finally:
        await client.aclose()
    assert languages["languages"][0]["language"] == "en-US"
    assert voices["default_voice"] == "illyvoip-emma"
    assert seen[0].url.params["context"] == "voice_api"
    assert seen[1].url.params["context"] == "voice_api"
    assert seen[1].url.params["language"] == "en-US"


def test_idempotency_key_is_deterministic_and_bounded() -> None:
    campaign_id = uuid.uuid4()
    tracking_uuid = uuid.uuid4()
    first = IllyVoIPService.build_idempotency_key(
        campaign_id, tracking_uuid, "create"
    )
    second = IllyVoIPService.build_idempotency_key(
        campaign_id, tracking_uuid, "create"
    )
    speak = IllyVoIPService.build_idempotency_key(
        campaign_id, tracking_uuid, "speak"
    )
    assert first == second
    assert first != speak
    assert 8 <= len(first) <= 128
    assert 8 <= len(speak) <= 128
    assert str(campaign_id) not in first


def test_estimate_speech_seconds_is_bounded() -> None:
    service = IllyVoIPService(
        settings=_settings(
            illyvoip_tts_chars_per_second=10.0,
            illyvoip_tts_padding_seconds=2.0,
            illyvoip_max_speech_wait_seconds=10,
        ),
        client=_client(lambda _: _json({})),
    )
    assert service.estimate_speech_seconds("a" * 20) == 4
    assert service.estimate_speech_seconds("a" * 2000) == 10


async def _run_with_states(states: list[dict], **overrides: object) -> dict:
    """Place one call whose status endpoint replays ``states`` in order."""
    calls: list[httpx.Request] = []
    index = {"value": 0}
    base = _answered_handler(calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            calls.append(request)
            position = min(index["value"], len(states) - 1)
            index["value"] += 1
            return _json(states[position])
        return base(request)

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(**overrides), client=client)
        return await service.place_vishing_call(
            "+967770447622", "Hello from the security team."
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ringing_then_answer_is_reported_as_verified_ring() -> None:
    """An observed ringing phase is what makes an answer trustworthy."""
    result = await _run_with_states(
        [
            _call_status(state="ringing", call_status="ringing"),
            _call_status(
                state="active",
                call_status="active",
                answered_at="2026-11-12 12:00:05+00:00",
            ),
        ],
        illyvoip_min_answer_delay_seconds=0.0,
    )
    assert result["rang"] is True
    assert result["answer_delay_seconds"] is not None
    assert result["answer_suspect_auto"] is False


@pytest.mark.asyncio
async def test_answer_faster_than_threshold_is_flagged_as_suspect() -> None:
    """A sub-second answer after ringing is a machine, not a person."""
    result = await _run_with_states(
        [
            _call_status(state="ringing", call_status="ringing"),
            _call_status(
                state="active",
                call_status="active",
                answered_at="2026-11-12 12:00:05+00:00",
            ),
        ],
        illyvoip_min_answer_delay_seconds=1.0,
    )
    assert result["rang"] is True
    assert result["answer_suspect_auto"] is True


@pytest.mark.asyncio
async def test_answer_without_ringing_is_flagged_as_suspect() -> None:
    """An instant active session with no ringing is a voicemail/announcement."""
    result = await _run_with_states(
        [
            _call_status(
                state="active",
                call_status="active",
                answered_at="2026-11-12 12:00:01+00:00",
            )
        ]
    )
    assert result["rang"] is False
    assert result["answer_suspect_auto"] is True


@pytest.mark.asyncio
async def test_unanswered_call_reports_whether_it_rang() -> None:
    """A failed call carries the ringing evidence for the audit trail."""
    calls: list[httpx.Request] = []
    answered = _answered_handler(calls)
    index = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            calls.append(request)
            index["value"] += 1
            if index["value"] == 1:
                return _json(_call_status(state="ringing", call_status="ringing"))
            return _json(
                _call_status(
                    state="ended",
                    call_status="failed",
                    terminal=True,
                    failure_reason="The call could not be completed.",
                )
            )
        return answered(request)

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPCallFailedError) as excinfo:
            await service.place_vishing_call(
                "+967770447622", "Hello from the security team."
            )
    finally:
        await client.aclose()
    assert excinfo.value.fields.get("rang") is True


def test_detect_tts_language_switches_for_arabic_scripts() -> None:
    """The script picks the TTS language when the caller did not choose one."""
    assert (
        detect_tts_language(
            "مرحبًا، هذا اتصال من قسم تقنية المعلومات بخصوص جلستك",
            default="en-US",
            arabic="ar-AR",
        )
        == "ar-AR"
    )
    # Mixed Arabic with English product names still needs an Arabic voice.
    assert (
        detect_tts_language(
            "تم إيقاف حسابك على VPN، افتح الرابط",
            default="en-US",
            arabic="ar-AR",
        )
        == "ar-AR"
    )
    assert (
        detect_tts_language(
            "Hello from the security team.", default="en-US", arabic="ar-AR"
        )
        == "en-US"
    )
    assert detect_tts_language("12345", default="en-US", arabic="ar-AR") == "en-US"
    assert detect_tts_language("نص", default="en-US", arabic=None) == "en-US"


def _answered_handler(requests: list[httpx.Request]):
    """Return a transport handler that answers every call-control request."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "state": "accepted",
                }
            )
        if path.endswith("/status"):
            return _json(
                _call_status(
                    state="active",
                    call_status="active",
                    answered_at="2026-11-12 12:00:05+00:00",
                )
            )
        if path.endswith("/speak"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_test",
                    "media": "vcm2.test-media",
                }
            )
        if path.endswith("/wait"):
            return _json(
                {"status": "success", "call_control_id": "vapi_test", "seconds": 1}
            )
        if path.endswith("/hangup"):
            return _json({"status": "success", "call_control_id": "vapi_test"})
        return _json({"status": "error", "message": "unexpected path"}, 500)

    return handler


@pytest.mark.asyncio
async def test_arabic_script_speaks_with_arabic_language() -> None:
    """An Arabic script is never sent to the English default voice."""
    requests: list[httpx.Request] = []
    client = _client(_answered_handler(requests))
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        await service.place_vishing_call(
            "+967774369478",
            "مرحبًا، هذا اتصال من قسم تقنية المعلومات بخصوص جلستك.",
        )
    finally:
        await client.aclose()

    speak = next(r for r in requests if r.url.path.endswith("/speak"))
    speak_body = json.loads(speak.content)
    assert speak_body["language"] == "ar-AR"


@pytest.mark.asyncio
async def test_explicit_language_wins_over_script_detection() -> None:
    """An operator-selected language is never overridden by detection."""
    requests: list[httpx.Request] = []
    client = _client(_answered_handler(requests))
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        await service.place_vishing_call(
            "+967774369478",
            "مرحبًا، هذا اتصال من قسم تقنية المعلومات.",
            language="en-GB",
        )
    finally:
        await client.aclose()

    speak = next(r for r in requests if r.url.path.endswith("/speak"))
    assert json.loads(speak.content)["language"] == "en-GB"


@pytest.mark.asyncio
async def test_playback_wait_timeout_does_not_fail_a_completed_call() -> None:
    """A slow ``/wait`` must not turn an answered call into a 502."""
    requests: list[httpx.Request] = []
    answered = _answered_handler(requests)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/wait"):
            requests.append(request)
            raise httpx.ReadTimeout("wait timed out", request=request)
        return answered(request)

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.place_vishing_call(
            "+967774369478",
            "مرحبًا، هذه مكالمة تجريبية من قسم تقنية المعلومات.",
        )
    finally:
        await client.aclose()

    assert result["call_control_id"] == "vapi_test"
    assert result["tts_media"] == "vcm2.test-media"
    # The call is still closed explicitly instead of being left running.
    assert any(r.url.path.endswith("/hangup") for r in requests)


@pytest.mark.asyncio
async def test_english_script_keeps_the_configured_default_language() -> None:
    """Detection must not change the existing English behaviour."""
    requests: list[httpx.Request] = []
    client = _client(_answered_handler(requests))
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        await service.place_vishing_call(
            "+967774369478", "Hello from the security team."
        )
    finally:
        await client.aclose()

    speak = next(r for r in requests if r.url.path.endswith("/speak"))
    assert json.loads(speak.content)["language"] == "en-US"


@pytest.mark.asyncio
async def test_hangup_retries_provider_503_until_call_is_cut() -> None:
    """IllyVoIP answers 503 "Unable to terminate" while a call still rings."""
    attempts = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["value"] += 1
        if attempts["value"] < 3:
            return _json(
                {
                    "status": "error",
                    "message": "Unable to terminate the call right now.",
                    "error_code": "service_unavailable",
                },
                status_code=503,
            )
        return _json({"status": "success", "call_control_id": "vapi_test"})

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.hangup("vapi_test")
    finally:
        await client.aclose()
    assert result["status"] == "success"
    assert attempts["value"] == 3


@pytest.mark.asyncio
async def test_ring_only_call_hangs_up_at_first_ring_without_speaking() -> None:
    """Verification calls must stop at the ring: no answer wait, no TTS."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        paths.append(path)
        if path.endswith("/call-control/calls"):
            return _json({"status": "success", "call_control_id": "vapi_ring", "state": "accepted"})
        if path.endswith("/call-control/status"):
            return _json(_call_status(state="ringing", call_status="ringing"))
        if path.endswith("/call-control/hangup"):
            return _json({"status": "success", "call_control_id": "vapi_ring"})
        raise AssertionError(f"unexpected path {path}")

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.ring_only_call("+966500000000")
    finally:
        await client.aclose()

    assert result["rang"] is True
    assert result["call_control_id"] == "vapi_ring"
    assert any(p.endswith("/hangup") for p in paths)
    assert not any(p.endswith("/speak") for p in paths)
    assert not any(p.endswith("/wait") for p in paths)


@pytest.mark.asyncio
async def test_ring_only_call_accepts_failed_hangup_when_provider_already_ended() -> None:
    """A 503 hangup is harmless when the carrier already ended the call."""
    status_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/call-control/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_ring",
                    "state": "accepted",
                }
            )
        if path.endswith("/call-control/status"):
            status_count["value"] += 1
            if status_count["value"] == 1:
                return _json(_call_status(state="ringing", call_status="ringing"))
            return _json(
                _call_status(
                    state="ended",
                    call_status="failed",
                    terminal=True,
                    failure_reason="The call could not be completed.",
                )
            )
        if path.endswith("/call-control/hangup"):
            return _json(
                {"status": "error", "message": "Unable to terminate the call right now"},
                status_code=503,
            )
        raise AssertionError(f"unexpected path {path}")

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        result = await service.ring_only_call("+966500000000", ring_timeout_seconds=2)
    finally:
        await client.aclose()

    assert result["rang"] is True
    assert result["hangup"] is None
    assert result["state"] == "ended"
    assert status_count["value"] == 2


@pytest.mark.asyncio
async def test_ring_only_call_raises_when_hangup_fails_and_call_stays_live() -> None:
    """Leaving a ringing call live is a failure, not a successful ring test."""
    hangup_calls = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/call-control/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_ring",
                    "state": "accepted",
                }
            )
        if path.endswith("/call-control/status"):
            return _json(_call_status(state="ringing", call_status="ringing"))
        if path.endswith("/call-control/hangup"):
            hangup_calls["value"] += 1
            return _json(
                {"status": "error", "message": "Unable to terminate the call right now"},
                status_code=503,
            )
        raise AssertionError(f"unexpected path {path}")

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPCallFailedError) as exc_info:
            await service.ring_only_call("+966500000000", ring_timeout_seconds=2)
    finally:
        await client.aclose()

    exc = exc_info.value
    assert exc.error_code == "hangup_failed"
    assert exc.status_code == 503
    assert exc.fields["call_control_id"] == "vapi_ring"
    assert exc.fields["rang"] is True
    assert exc.fields["ring_seconds"] >= 0
    assert exc.fields["status"]["state"] == "ringing"
    assert hangup_calls["value"] == 3


@pytest.mark.asyncio
async def test_ring_only_call_hangs_up_an_early_answer() -> None:
    """If the handset answers before ringing is observed, cut it immediately."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        paths.append(path)
        if path.endswith("/call-control/calls"):
            return _json(
                {
                    "status": "success",
                    "call_control_id": "vapi_ring",
                    "state": "accepted",
                }
            )
        if path.endswith("/call-control/status"):
            return _json(
                _call_status(
                    state="active",
                    call_status="active",
                    answered_at="2026-11-12 12:00:05+00:00",
                )
            )
        if path.endswith("/call-control/hangup"):
            return _json({"status": "success", "call_control_id": "vapi_ring"})
        raise AssertionError(f"unexpected path {path}")

    client = _client(handler)
    try:
        service = IllyVoIPService(settings=_settings(), client=client)
        with pytest.raises(IllyVoIPCallFailedError) as exc_info:
            await service.ring_only_call("+966500000000", ring_timeout_seconds=2)
    finally:
        await client.aclose()

    exc = exc_info.value
    assert exc.error_code == "call_failed"
    assert exc.fields["call_control_id"] == "vapi_ring"
    assert exc.fields["rang"] is False
    assert any(p.endswith("/hangup") for p in paths)
    assert not any(p.endswith("/speak") for p in paths)
