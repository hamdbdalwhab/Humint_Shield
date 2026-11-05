"""Elo-based adaptive difficulty engine.

The engine is deliberately small and deterministic so that the risk score is
auditable and easy to explain to administrators:

* every employee starts at **1000**;
* the first click on a simulated link costs **32** points;
* the first report of a simulated message earns **32** points;
* the score is clamped to ``0..2000`` so a long-running account cannot overflow
  an integer column or become impossible to recover.

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

from typing import Literal

INITIAL_ELO = 1000
MIN_ELO = 0
MAX_ELO = 2000
CLICK_ELO_DELTA = -32
REPORT_ELO_DELTA = 32

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
    "CLICK_ELO_DELTA",
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
    "clamp_elo",
    "difficulty_band",
    "difficulty_range",
    "threat_label",
    "threat_level_for_elo",
]
