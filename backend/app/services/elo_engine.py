"""Elo-based adaptive difficulty engine.

The engine is deliberately small and deterministic so that the risk score is
auditable and easy to explain to administrators:

* every employee starts at **1000**;
* each channel owns a weight (Email 300, QR 200, Smishing/Vishing 200,
  USB/Physical 150);
* each outcome moves a fixed fraction of that weight (reported +25%, opened
  -5%, clicked -15%, submitted -30%, ignored 0%);
* the template difficulty multiplies the movement (easy 1x, medium 1.5x,
  hard 2x);
* the score is clamped to ``0..2000`` so a long-running account cannot overflow
  an integer column or become impossible to recover.

The legacy fixed ``CLICK_ELO_DELTA`` / ``REPORT_ELO_DELTA`` constants remain for
backwards-compatible callers; campaign events use :func:`smart_elo_delta`.

Difficulty bands and threat labels are monotonic.  The Elo bands are the
contract used by the campaign launcher; the threat labels are the human-facing
view of the same score.

===========  =================  ============  ==================
Elo           Template band      Difficulty    Threat level
===========  =================  ============  ==================
``< 900``     easy               1-3           high (800-899) / critical (<800)
``900-1100``  medium             4-7           medium
``> 1100``    hard               8-10          low
===========  =================  ============  ==================
"""
from __future__ import annotations

import math
from typing import Literal

INITIAL_ELO = 1000
MIN_ELO = 0
MAX_ELO = 2000

#: Legacy fixed deltas.  Kept for callers that score an event without a
#: campaign template (and for backwards-compatible imports); the smart engine
#: below is the authoritative model for new campaign events.
CLICK_ELO_DELTA = -32
REPORT_ELO_DELTA = 32

#: Channel weight allocation.  The five primary channels sum to the 1000-point
#: starting score, so each channel owns a proportional share of the rating.
CHANNEL_WEIGHTS: dict[str, int] = {
    "email": 300,
    "qr": 200,
    "vishing": 200,
    "smishing": 200,
    "sms": 200,
    "whatsapp": 200,
    "pretexting": 200,
    "usb": 150,
    "physical": 150,
}
DEFAULT_CHANNEL_WEIGHT = 300

#: Fraction of the channel weight moved by each outcome.  ``reported`` is the
#: only positive behaviour; ``ignored`` is deliberately neutral.
ACTION_IMPACT_RATIOS: dict[str, float] = {
    "reported": 0.25,
    "ignored": 0.0,
    "opened": 0.05,
    "clicked": 0.15,
    "submitted": 0.30,
}

#: Campaign difficulty multipliers: 1-3 easy, 4-7 medium, 8-10 hard.
DIFFICULTY_MULTIPLIERS: dict[str, float] = {
    "easy": 1.0,
    "medium": 1.5,
    "hard": 2.0,
}

ACTION_NAMES = tuple(ACTION_IMPACT_RATIOS)

#: Channel-specific outcomes for the advanced simulation channels.
#:
#: A QR scan by itself is score-neutral: the scan only opens the simulated
#: mobile sign-in page.  The quishing penalty is applied once, when the
#: recipient actually submits the credential form.
QR_SCAN_ELO_DELTA = 0
QR_CREDENTIAL_ELO_DELTA = -25
QR_REPEAT_EVASION_ELO_DELTA = -15
OTP_SUBMISSION_ELO_DELTA = -15
USB_OPEN_ELO_DELTA = -30
#: Smishing: opening the lure link is score-neutral; submitting the form on
#: the SMS landing page is the failure outcome.
SMS_CREDENTIAL_ELO_DELTA = -40
SMS_REPORT_ELO_DELTA = 20
VISHING_CREDENTIAL_ELO_DELTA = -30
VISHING_REPORT_ELO_DELTA = 20
PRETEXTING_FRAUD_ELO_DELTA = -30
PRETEXTING_REPORT_ELO_DELTA = 20

DifficultyBand = Literal["easy", "medium", "hard"]
ThreatLevel = Literal["low", "medium", "high", "critical"]

#: Inclusive difficulty range for each Elo band.
DIFFICULTY_RANGES: dict[DifficultyBand, tuple[int, int]] = {
    "easy": (1, 3),
    "medium": (4, 7),
    "hard": (8, 10),
}

THREAT_LABELS: dict[ThreatLevel, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "critical": "Critical",
}

THREAT_LABELS_AR: dict[ThreatLevel, str] = {
    "low": "منخفض",
    "medium": "متوسط",
    "high": "مرتفع",
    "critical": "حرج",
}


def clamp_elo(value: int | float | None) -> int:
    """Return ``value`` coerced to an integer inside the supported range.

    Args:
        value: Current Elo, possibly ``None`` for legacy rows.

    Returns:
        A clamped integer.  ``None`` is treated as :data:`INITIAL_ELO`.
    """
    if value is None:
        return INITIAL_ELO
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return INITIAL_ELO
    return max(MIN_ELO, min(MAX_ELO, numeric))


def apply_elo_delta(current: int | float | None, delta: int) -> int:
    """Apply a signed Elo delta and clamp the result.

    Args:
        current: Current Elo (``None`` -> 1000).
        delta: Signed change (use :data:`CLICK_ELO_DELTA` or
            :data:`REPORT_ELO_DELTA` for the standard events).

    Returns:
        The new, clamped Elo.
    """
    return clamp_elo(clamp_elo(current) + int(delta))


def apply_click(current: int | float | None) -> int:
    """Return the Elo after a first click (``-32``)."""
    return apply_elo_delta(current, CLICK_ELO_DELTA)


def apply_report(current: int | float | None) -> int:
    """Return the Elo after a first report (``+32``)."""
    return apply_elo_delta(current, REPORT_ELO_DELTA)


def normalize_channel(channel: str | None) -> str:
    """Return the canonical channel key used by the weight table."""
    value = (channel or "email").strip().lower()
    if value in {"sms", "whatsapp"}:
        # Both mobile-message channels are treated as smishing for scoring.
        return "smishing"
    if value in {"pretexting"}:
        return "vishing"
    return value if value in CHANNEL_WEIGHTS else "email"


def channel_weight(channel: str | None) -> int:
    """Return the point pool allocated to a channel (defaults to email)."""
    return CHANNEL_WEIGHTS.get(normalize_channel(channel), DEFAULT_CHANNEL_WEIGHT)


def difficulty_multiplier(difficulty: int | float | None) -> float:
    """Return the multiplier for a template difficulty of ``1..10``.

    Difficulty is clamped into the 1-10 contract.  Unknown values fall back to
    the medium band so legacy rows remain deterministic.
    """
    try:
        value = int(round(float(difficulty))) if difficulty is not None else 5
    except (TypeError, ValueError):
        value = 5
    value = max(1, min(10, value))
    if value <= 3:
        return DIFFICULTY_MULTIPLIERS["easy"]
    if value <= 7:
        return DIFFICULTY_MULTIPLIERS["medium"]
    return DIFFICULTY_MULTIPLIERS["hard"]


def smart_elo_delta(
    channel: str | None,
    action: str,
    difficulty: int | float | None = None,
) -> int:
    """Calculate the signed Elo change for one channel outcome.

    Args:
        channel: Campaign channel (``email``, ``qr``, ``vishing``, ``usb``...).
        action: One of ``reported``, ``ignored``, ``opened``, ``clicked`` or
            ``submitted``.
        difficulty: Template difficulty (1-10); ``None`` uses the medium band.

    Returns:
        A signed integer delta.  Positive actions are positive; failures are
        negative.  A non-zero outcome always moves at least one point.
    """
    key = (action or "ignored").strip().lower()
    ratio = ACTION_IMPACT_RATIOS.get(key)
    if ratio is None:
        raise ValueError(f"unsupported Elo action: {action!r}")
    if ratio == 0:
        return 0
    raw = channel_weight(channel) * ratio * difficulty_multiplier(difficulty)
    # Standard half-up rounding (Python's round() uses banker's rounding, which
    # would turn 22.5 into 22 and make the score table surprising).
    magnitude = max(1, int(math.floor(raw + 0.5)))
    return magnitude if key == "reported" else -magnitude


def apply_smart_action(
    current: int | float | None,
    channel: str | None,
    action: str,
    difficulty: int | float | None = None,
) -> int:
    """Apply a smart channel/action delta to an Elo score."""
    return apply_elo_delta(current, smart_elo_delta(channel, action, difficulty))


def awareness_level_for_elo(elo: int | float | None) -> str:
    """Return a certificate-friendly awareness level for a final Elo score."""
    score = clamp_elo(elo)
    if score >= 1101:
        return "Advanced"
    if score >= 900:
        return "Aware"
    if score >= 700:
        return "Developing"
    return "At Risk"


AWARENESS_LEVELS_AR: dict[str, str] = {
    "Advanced": "متقدم",
    "Aware": "واعٍ",
    "Developing": "نامٍ",
    "At Risk": "معرّض للخطر",
}


def awareness_level_ar(elo: int | float | None) -> str:
    """Return the Arabic certificate awareness label."""
    return AWARENESS_LEVELS_AR[awareness_level_for_elo(elo)]


def difficulty_band(elo: int | float | None) -> DifficultyBand:
    """Map an Elo score to the launcher's difficulty band.

    The thresholds are exactly the product contract: ``<900`` easy,
    ``900-1100`` medium (inclusive), and ``>1100`` hard.
    """
    score = clamp_elo(elo)
    if score < 900:
        return "easy"
    if score <= 1100:
        return "medium"
    return "hard"


def difficulty_range(elo: int | float | None) -> tuple[int, int]:
    """Return the inclusive template-difficulty range for an Elo score."""
    return DIFFICULTY_RANGES[difficulty_band(elo)]


def threat_level_for_elo(elo: int | float | None) -> ThreatLevel:
    """Map an Elo score to a four-level threat badge.

    The mapping is monotonic and aligned with the difficulty bands:

    * ``>= 1101`` -> ``low``
    * ``900..1100`` -> ``medium`` (the starting state)
    * ``800..899`` -> ``high``
    * ``< 800`` -> ``critical``

    A score can enter the easy template band (``<900``) while still being
    ``high`` rather than ``critical``; that is intentional, because the
    launcher's band and the executive threat label answer different questions.
    """
    score = clamp_elo(elo)
    if score >= 1101:
        return "low"
    if score >= 900:
        return "medium"
    if score >= 800:
        return "high"
    return "critical"


def threat_label(elo: int | float | None, *, arabic: bool = False) -> str:
    """Return the human-readable label for an Elo score."""
    level = threat_level_for_elo(elo)
    return (THREAT_LABELS_AR if arabic else THREAT_LABELS)[level]


__all__ = [
    "ACTION_IMPACT_RATIOS",
    "ACTION_NAMES",
    "AWARENESS_LEVELS_AR",
    "CHANNEL_WEIGHTS",
    "CLICK_ELO_DELTA",
    "DEFAULT_CHANNEL_WEIGHT",
    "DIFFICULTY_MULTIPLIERS",
    "DIFFICULTY_RANGES",
    "DifficultyBand",
    "INITIAL_ELO",
    "MAX_ELO",
    "MIN_ELO",
    "OTP_SUBMISSION_ELO_DELTA",
    "PRETEXTING_FRAUD_ELO_DELTA",
    "PRETEXTING_REPORT_ELO_DELTA",
    "QR_CREDENTIAL_ELO_DELTA",
    "QR_REPEAT_EVASION_ELO_DELTA",
    "QR_SCAN_ELO_DELTA",
    "REPORT_ELO_DELTA",
    "THREAT_LABELS",
    "THREAT_LABELS_AR",
    "ThreatLevel",
    "apply_click",
    "apply_elo_delta",
    "apply_report",
    "apply_smart_action",
    "awareness_level_ar",
    "awareness_level_for_elo",
    "channel_weight",
    "clamp_elo",
    "difficulty_band",
    "difficulty_multiplier",
    "difficulty_range",
    "normalize_channel",
    "smart_elo_delta",
    "threat_label",
    "threat_level_for_elo",
]
