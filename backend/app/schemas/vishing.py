"""Schemas for the real IllyVoIP vishing channel."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


class VishingCallRequest(BaseModel):
    """Request to place one real outbound vishing call.

    A call targets either a stored employee (``employee_id``) or an explicitly
    authorised E.164 destination (``to_phone``).  Supplying both is rejected so
    the audit trail can never be ambiguous.  Direct destinations are restricted
    to administrators by the endpoint.
    """

    employee_id: uuid.UUID | None = None
    to_phone: str | None = Field(default=None, max_length=32)
    script: str = Field(min_length=1, max_length=2000)
    campaign_id: uuid.UUID | None = None
    tracking_uuid: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=35)
    voice: str | None = Field(default=None, max_length=80)
    #: Verified/owned caller ID to present.  Must differ from the destination:
    #: presenting the callee's own number makes carriers drop the call, which is
    #: why the account default can look "answered" while the phone never rings.
    from_phone: str | None = Field(default=None, max_length=32)
    #: Optional SIP identity override for operators with several lines.
    sip_user_id: str | None = Field(default=None, max_length=64)
    answer_timeout_seconds: float | None = Field(default=None, ge=5, le=120)
    record: bool | None = None
    #: Optional caller-supplied retry key.  Reusing it after an ambiguous
    #: network failure makes the create/speak/hangup actions idempotent.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    #: Explicit human confirmation that the destination is an authorised
    #: employee/test number.  This prevents an accidental production call.
    confirm_authorized: bool = False

    @model_validator(mode="after")
    def _validate_destination(self) -> "VishingCallRequest":
        has_employee = self.employee_id is not None
        has_phone = bool((self.to_phone or "").strip())
        if not has_employee and not has_phone:
            raise ValueError("employee_id or to_phone is required")
        if has_employee and has_phone:
            raise ValueError("provide employee_id or to_phone, not both")
        if self.tracking_uuid is not None and self.campaign_id is None:
            raise ValueError("campaign_id is required when tracking_uuid is provided")
        return self


class VishingCallResponse(BaseModel):
    """Result of a completed real call-control flow."""

    success: bool = True
    provider: str = "illyvoip"
    call_control_id: str
    employee_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    tracking_uuid: uuid.UUID | None = None
    to_phone_masked: str
    state: str = ""
    call_status: str = ""
    answered_at: str | None = None
    ended_at: str | None = None
    failure_reason: str | None = None
    tts_media: str | None = None
    tts_charge: dict[str, Any] | None = None
    hangup: dict[str, Any] | None = None
    duration_seconds: float = 0.0
    #: Whether the destination actually rang before the provider reported an
    #: answer.  ``answered_at`` alone cannot distinguish a person from a
    #: voicemail, IVR or carrier announcement.
    rang: bool = False
    #: Seconds between the first ringing observation and the answer.
    answer_delay_seconds: float | None = None
    #: ``True`` when the answer looked automatic rather than a person picking up.
    answer_suspect_auto: bool = False


class VishingCallStatusResponse(BaseModel):
    """Provider status for one previously created call."""

    provider: str = "illyvoip"
    call_control_id: str
    state: str = ""
    call_status: str = ""
    terminal: bool = False
    answered_at: str | None = None
    ended_at: str | None = None
    failure_reason: str | None = None


class VishingHangupResponse(BaseModel):
    """Result of an explicit hangup."""

    success: bool = True
    provider: str = "illyvoip"
    call_control_id: str
    message: str = ""
    terminated_channels: int = 0
    idempotent: bool = False


class VishingConfigResponse(BaseModel):
    """Non-secret readiness for the real vishing channel."""

    provider: str = "illyvoip"
    valid: bool
    configured: bool
    missing: list[str] = Field(default_factory=list)
    #: Optional identity settings (SIP user, caller ID) that are unset.  The
    #: provider then applies the account defaults; this never blocks a call.
    warnings: list[str] = Field(default_factory=list)
    base_url: str = ""
    sip_user_id: str | None = None
    caller_id: str | None = None
    caller_id_valid: bool = False
    tts_language: str | None = None
    tts_voice: str | None = None
    record_calls: bool = False
    sandbox: bool = False
    api_reachable: bool | None = None
    backend_status: str | None = None
    message: str | None = None
    error: str | None = None
    hint: str | None = None
    status_code: int | None = None
    error_code: str | None = None


__all__ = [
    "VishingCallRequest",
    "VishingCallResponse",
    "VishingCallStatusResponse",
    "VishingConfigResponse",
    "VishingHangupResponse",
]
