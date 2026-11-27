"""GSM-7 / UCS-2 segmentation used by the SMS channel."""
from __future__ import annotations

import pytest

from app.services.sms_segments import (
    CONCAT_GSM7,
    CONCAT_UCS2,
    SINGLE_GSM7,
    SINGLE_UCS2,
    fits_single_segment,
    segment_info,
)


def test_empty_message_has_no_segments() -> None:
    info = segment_info(None)
    assert info.segments == 0
    assert info.units == 0
    assert info.encoding == "gsm-7"
    assert segment_info("") == info


def test_latin_message_uses_one_gsm7_segment() -> None:
    info = segment_info("A" * SINGLE_GSM7)
    assert info.encoding == "gsm-7"
    assert info.units == SINGLE_GSM7
    assert info.segments == 1
    assert info.remaining == 0
    assert fits_single_segment("A" * SINGLE_GSM7)


def test_latin_message_over_160_is_concatenated() -> None:
    info = segment_info("A" * (SINGLE_GSM7 + 1))
    assert info.segments == 2
    assert info.characters_per_segment == CONCAT_GSM7
    assert info.remaining == (2 * CONCAT_GSM7) - (SINGLE_GSM7 + 1)


def test_arabic_message_is_ucs2_and_only_sixty_five_fit() -> None:
    """Arabic is UCS-2: 70 characters per segment, never 160."""
    seventy = "ش" * SINGLE_UCS2
    info = segment_info(seventy)
    assert info.encoding == "ucs-2"
    assert info.segments == 1
    assert info.remaining == 0

    more = segment_info("ش" * (SINGLE_UCS2 + 1))
    assert more.segments == 2
    assert more.characters_per_segment == CONCAT_UCS2


def test_arabic_message_of_170_characters_is_three_segments() -> None:
    """The template cap is 170 characters, which is three UCS-2 segments."""
    info = segment_info("ا" * 170)
    assert info.encoding == "ucs-2"
    assert info.segments == 3


def test_extended_gsm_characters_cost_two_septets() -> None:
    info = segment_info("€" * 80)
    assert info.encoding == "gsm-7"
    assert info.units == 160
    assert info.segments == 1
    assert not fits_single_segment("€" * 81)


def test_emoji_counts_as_two_utf16_units() -> None:
    info = segment_info("🙂")
    assert info.encoding == "ucs-2"
    assert info.units == 2
    assert info.segments == 1


def test_short_link_brings_a_capped_body_back_over_one_segment() -> None:
    """170 characters + a 32-character link is two UCS-2 segments, not one."""
    body = "ش" * 170
    info = segment_info(f"{body} https://sms.example.com/s/abc123")
    assert info.segments >= 3
    assert not fits_single_segment(f"{body} https://sms.example.com/s/abc123")


@pytest.mark.parametrize("segments", [1, 2, 5])
def test_as_dict_is_json_friendly(segments: int) -> None:
    info = segment_info("A" * (150 * segments))
    payload = info.as_dict()
    assert payload["segments"] == info.segments
    assert set(payload) == {
        "encoding",
        "units",
        "segments",
        "characters_per_segment",
        "remaining",
    }
