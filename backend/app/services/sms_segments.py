"""GSM-7 / UCS-2 segmentation for outbound SMS.

An SMS is not billed or delivered per character but per *segment*:

* GSM-7 (Latin) fits **160** characters in one segment and **153** per
  segment once the message is concatenated.
* UCS-2 (Arabic, emoji, any non-GSM character) fits only **70** characters in
  one segment and **67** per concatenated segment.

Arabic lures are therefore three segments long even when they are "only" 170
characters.  Knowing the real segment count keeps cost forecasts, campaign
reports and the interaction ledger accurate, and lets the launcher warn an
operator before a message silently triples in price.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Characters that a GSM 03.38 handset encodes in a single septet.
GSM7_BASIC = frozenset(
    "@\u00a3$\u00a5\u00e8\u00e9\u00f9\u00ec\u00f2\u00c7\n\u00d8\u00f8\r"
    "\u00c5\u00e5\u0394_\u03a6\u0393\u039b\u03a9\u03a0\u03a8\u03a3\u0398\u039e"
    "\u00c6\u00e6\u00df\u00c9 !\"#\u00a4%&'()*+,-./0123456789:;<=>?"
    "\u00a1ABCDEFGHIJKLMNOPQRSTUVWXYZ\u00c4\u00d6\u00d1\u00dc\u00a7"
    "\u00bfabcdefghijklmnopqrstuvwxyz\u00e4\u00f6\u00f1\u00fc\u00e0"
)

#: GSM 03.38 extension table: each character costs two septets.
GSM7_EXTENDED = frozenset("^{}\\[~]|\u20ac")

SINGLE_GSM7 = 160
CONCAT_GSM7 = 153
SINGLE_UCS2 = 70
CONCAT_UCS2 = 67


@dataclass(frozen=True, slots=True)
class SmsSegments:
    """Segmentation facts for one outbound message body."""

    encoding: str
    units: int
    segments: int
    characters_per_segment: int
    remaining: int

    @property
    def concatenated(self) -> bool:
        """Return ``True`` when the message spans more than one segment."""
        return self.segments > 1

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation for logs and API payloads."""
        return {
            "encoding": self.encoding,
            "units": self.units,
            "segments": self.segments,
            "characters_per_segment": self.characters_per_segment,
            "remaining": self.remaining,
        }


def _utf16_units(text: str) -> int:
    """Return the number of 16-bit code units (UCS-2) the text occupies."""
    return len(text.encode("utf-16-le")) // 2


def segment_info(text: str | None) -> SmsSegments:
    """Return how many SMS segments ``text`` occupies.

    Args:
        text: Message body; ``None`` is treated as an empty message.

    Returns:
        An :class:`SmsSegments` describing the encoding, the payable units and
        the number of segments.  An empty body reports ``segments == 0``.
    """
    body = text or ""
    if not body:
        return SmsSegments("gsm-7", 0, 0, SINGLE_GSM7, SINGLE_GSM7)

    if all(ch in GSM7_BASIC or ch in GSM7_EXTENDED for ch in body):
        units = len(body) + sum(1 for ch in body if ch in GSM7_EXTENDED)
        encoding = "gsm-7"
        single, concat = SINGLE_GSM7, CONCAT_GSM7
    else:
        units = _utf16_units(body)
        encoding = "ucs-2"
        single, concat = SINGLE_UCS2, CONCAT_UCS2

    if units <= single:
        return SmsSegments(encoding, units, 1, single, single - units)

    segments = math.ceil(units / concat)
    return SmsSegments(
        encoding,
        units,
        segments,
        concat,
        segments * concat - units,
    )


def fits_single_segment(text: str | None) -> bool:
    """Return ``True`` when ``text`` is one billable SMS segment."""
    return segment_info(text).segments <= 1


__all__ = [
    "CONCAT_GSM7",
    "CONCAT_UCS2",
    "GSM7_BASIC",
    "GSM7_EXTENDED",
    "SINGLE_GSM7",
    "SINGLE_UCS2",
    "SmsSegments",
    "fits_single_segment",
    "segment_info",
]
