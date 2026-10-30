"""Stable template-personalisation contract.

The implementation is kept in :mod:`app.services.template_service`; this module
provides the import path and a single-call helper used by the Email Channel.
It replaces ``{{first_name}}``, ``{{company_name}}`` and the other declared
variables, appends the 1x1 open-tracking pixel, and routes every anchor through
the click-tracking endpoint.
"""
from __future__ import annotations

from typing import Any

from app.services.template_service import (
    TRANSPARENT_GIF,
    TemplatePersonalizer,
    build_click_url,
    build_tracking_url,
    extract_links,
    html_to_text,
)


def personalize_template(
    template: Any,
    employee: Any,
    organization: Any,
    tracking_uuid: str,
    *,
    base_url: str | None = None,
    short_code: str | None = None,
) -> dict[str, str]:
    """Render a template for one employee.

    Args:
        template: Stored template with ``subject`` and ``body_html``.
        employee: Human asset supplying the variable values.
        organization: Organization supplying ``company_name``.
        tracking_uuid: Per-recipient UUID embedded in the pixel and links.
        base_url: Override for the public base URL.
        short_code: Optional short code for link shortener.

    Returns:
        ``{"subject": str, "html_content": str}`` ready for the provider.
    """
    personalizer = TemplatePersonalizer()
    return personalizer.personalize(
        template,
        employee,
        organization,
        tracking_uuid,
        base_url=base_url,
        short_code=short_code,
    )


__all__ = [
    "TRANSPARENT_GIF",
    "TemplatePersonalizer",
    "build_click_url",
    "build_tracking_url",
    "extract_links",
    "html_to_text",
    "personalize_template",
]
