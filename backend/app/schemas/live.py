"""Schemas for the live campaign monitoring board.

The board is polled every couple of seconds while a simulation is running, so
the payload is deliberately flat, JSON-friendly and free of nested ledger rows.
It carries everything needed to render a live card per recipient: the status
funnel, every transition timestamp, the durations between them, the last
observed event with its IP and user agent, and the outcome counters.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class LiveCampaign(BaseModel):
    """Campaign header shown on the live board."""

    id: uuid.UUID
    name: str
    channel: str = "email"
    status: str
    template_name: str | None = None
    difficulty_level: int | None = None
    total_targets: int = 0
    sent_count: int = 0
    failed_count: int = 0
    created_at: datetime | None = None
    launched_at: datetime | None = None
    completed_at: datetime | None = None
    #: Whole seconds since the campaign was launched.
    elapsed_seconds: int | None = None


class LiveSummary(BaseModel):
    """Aggregate funnel for the campaign, computed at request time."""

    total: int = 0
    sent: int = 0
    delivered: int = 0
    opened: int = 0
    clicked: int = 0
    form_viewed: int = 0
    submitted: int = 0
    reported: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    #: Recipients with any activity during the last five minutes.
    active_last_5m: int = 0
    open_rate: float = 0.0
    click_rate: float = 0.0
    form_view_rate: float = 0.0
    submission_rate: float = 0.0
    completion_rate: float = 0.0
    avg_seconds_to_open: float | None = None
    avg_seconds_to_click: float | None = None
    avg_seconds_to_submit: float | None = None


class LiveRecipient(BaseModel):
    """One row of the live board, one card in the dashboard."""

    employee_id: uuid.UUID
    tracking_id: uuid.UUID
    name: str
    email: str
    department: str | None = None
    job_title: str | None = None
    #: pending | sent | opened | clicked | form_viewed | submitted | completed | reported_safe | failed
    status: str
    #: Independent of the funnel: the recipient flagged the message as phishing.
    reported: bool = False
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    form_viewed_at: datetime | None = None
    submitted_at: datetime | None = None
    reported_at: datetime | None = None
    completed_at: datetime | None = None
    quiz_score: int | None = None
    quiz_total: int | None = None
    is_reported_safe: bool = False
    open_count: int = 0
    click_count: int = 0
    submission_count: int = 0
    interactions_count: int = 0
    #: Seconds between the send and each transition.
    seconds_to_open: float | None = None
    seconds_to_click: float | None = None
    seconds_to_form: float | None = None
    seconds_to_submit: float | None = None
    last_event_at: datetime | None = None
    last_event_type: str | None = None
    last_event_label: str | None = None
    seconds_since_last_event: float | None = None
    last_ip_address: str | None = None
    last_user_agent: str | None = None
    immunity_score: float | None = None
    behavioral_category: str | None = None
    password_length: int | None = None
    submitted_identifier: str | None = None


class LiveEvent(BaseModel):
    """Newest ledger entries, used by the activity ticker."""

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    event_type: str
    label: str
    occurred_at: datetime
    seconds_ago: float
    ip_address: str | None = None
    user_agent: str | None = None


class LiveBoard(BaseModel):
    """Complete payload for ``GET /email-campaigns/{id}/live``."""

    campaign: LiveCampaign
    summary: LiveSummary
    recipients: list[LiveRecipient]
    recent_events: list[LiveEvent]
    generated_at: datetime
