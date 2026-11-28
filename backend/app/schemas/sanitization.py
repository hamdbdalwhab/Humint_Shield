"""Input sanitisation for user-facing text fields.

Two levels are provided:

* :func:`sanitize_plain_text` — for names, titles and subjects where markup is
  never legitimate: dangerous constructs are rejected, then any remaining tags
  are stripped.
* :func:`reject_active_content` — for HTML bodies that are compiled and
  sanitised by the template pipeline: only active-content payloads are
  rejected, the markup itself is preserved.
"""
from __future__ import annotations

import re

#: Case-insensitive active-content markers that are never accepted in any field.
_DANGEROUS_PATTERNS = (
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"<\s*iframe\b", re.IGNORECASE),
    re.compile(r"<\s*object\b", re.IGNORECASE),
    re.compile(r"<\s*embed\b", re.IGNORECASE),
    re.compile(r"<\s*svg\b", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"\bvbscript\s*:", re.IGNORECASE),
    re.compile(r"\bon(?:error|load|click|mouseover|focus|submit)\s*=", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
)

#: Any HTML tag (used only for plain-text fields).
_TAG_RE = re.compile(r"<[^>]*>")
_WHITESPACE_RE = re.compile(r"\s+")


def _reject(value: str, field: str) -> None:
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"{field} contains active content that is not allowed "
                f"({pattern.pattern!r})"
            )


def reject_active_content(value: str | None, field: str = "value") -> str | None:
    """Reject scripts and event handlers while preserving legitimate markup."""
    if value is None:
        return None
    _reject(str(value), field)
    return value


def strip_html_tags(value: str) -> str:
    """Remove every HTML tag and collapse the resulting whitespace."""
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub("", value)).strip()


def sanitize_plain_text(value: str | None, field: str = "value") -> str | None:
    """Reject active content then strip markup from a plain-text field.

    Args:
        value: Raw input.
        field: Field name used in the error message.

    Returns:
        The cleaned value, or ``None`` when nothing was supplied.

    Raises:
        ValueError: When the value contains script/event-handler payloads.
    """
    if value is None:
        return None
    text = str(value)
    _reject(text, field)
    return strip_html_tags(text)


__all__ = [
    "reject_active_content",
    "sanitize_plain_text",
    "strip_html_tags",
]
