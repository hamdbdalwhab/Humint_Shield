"""Tests for the independent Elo adaptive-difficulty engine."""
from __future__ import annotations

from app.services.elo_engine import (
    CLICK_ELO_DELTA,
    INITIAL_ELO,
    REPORT_ELO_DELTA,
    apply_click,
    apply_elo_delta,
    apply_report,
    clamp_elo,
    difficulty_band,
    difficulty_range,
    threat_label,
    threat_level_for_elo,
)


def test_initial_click_and_report_values() -> None:
    """The product contract is 1000, -32 and +32."""
    assert INITIAL_ELO == 1000
    assert CLICK_ELO_DELTA == -32
    assert REPORT_ELO_DELTA == 32
    assert apply_click(1000) == 968
    assert apply_report(1000) == 1032
    assert apply_click(apply_report(1000)) == 1000


def test_clamping() -> None:
    """Elo is clamped to 0..2000 and legacy ``None`` starts at 1000."""
    assert clamp_elo(None) == 1000
    assert clamp_elo(-100) == 0
    assert clamp_elo(9999) == 2000
    assert apply_elo_delta(10, -32) == 0
    assert apply_elo_delta(1990, 32) == 2000


def test_difficulty_bands_boundaries() -> None:
    """The launcher's bands use <900, 900-1100 inclusive, and >1100."""
    assert difficulty_band(899) == "easy"
    assert difficulty_band(900) == "medium"
    assert difficulty_band(1100) == "medium"
    assert difficulty_band(1101) == "hard"
    assert difficulty_range(1000) == (4, 7)
    assert difficulty_range(500) == (1, 3)
    assert difficulty_range(1500) == (8, 10)


def test_threat_level_boundaries() -> None:
    """Threat badges are monotonic and aligned with the Elo bands."""
    assert threat_level_for_elo(799) == "critical"
    assert threat_level_for_elo(800) == "high"
    assert threat_level_for_elo(899) == "high"
    assert threat_level_for_elo(900) == "medium"
    assert threat_level_for_elo(1100) == "medium"
    assert threat_level_for_elo(1101) == "low"
    assert threat_label(799, arabic=True) == "حرج"
    assert threat_label(1200) == "Low"
