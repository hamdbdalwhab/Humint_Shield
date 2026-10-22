"""Template personalisation service.

Responsible for turning a stored :class:`~app.models.EmailTemplate` into a
recipient-specific subject and HTML body by:

1. substituting ``{{variable}}`` placeholders,
2. rewriting every ``<a href>`` so clicks are tracked, and
3. appending a 1x1 transparent tracking pixel.
"""
from __future__ import annotations

import html as html_lib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Matches ``{{ variable }}`` with optional surrounding whitespace.
VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
#: Matches an anchor tag's href attribute (single or double quoted).
HREF_RE = re.compile(r'(<a\b[^>]*?\bhref\s*=\s*)(["\'])(.*?)\2', re.IGNORECASE | re.DOTALL)
#: Matches an existing tracking pixel (so re-personalisation stays idempotent).
PIXEL_RE = re.compile(r'<img[^>]*src=["\'][^"\']*/api/v1/track/open/[^"\']*["\'][^>]*>',
                      re.IGNORECASE)

#: The 1x1 transparent GIF served by the open-tracking endpoint.
TRANSPARENT_GIF: bytes = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02"
    b"\x02D\x01\x00;"
)


class _LinkExtractor(HTMLParser):
    """Collect every ``href`` value found in a document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record ``href`` attributes on anchor tags."""
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def extract_links(html: str) -> list[str]:
    """Return every ``href`` in ``html`` preserving document order.

    Args:
        html: The HTML document to scan.

    Returns:
        A list of raw href values (as they appear in the markup).
    """
    parser = _LinkExtractor()
    try:
        parser.feed(html or "")
    except Exception:  # pragma: no cover - malformed markup
        logger.warning("extract_links_parse_error")
    return parser.links


class TemplatePersonalizer:
    """Render an email template for a specific employee."""

    def __init__(self, settings=None) -> None:
        """Store settings.

        Args:
            settings: Optional settings override (defaults to the global one).
        """
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def build_variables(
        self,
        template: Any,
        employee: Any,
        organization: Any,
        tracking_uuid: uuid.UUID | str,
        base_url: str | None = None,
        extra_vars: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Compute the variable mapping for a recipient.

        Args:
            template: The template being rendered.
            employee: The recipient :class:`~app.models.HumanAsset`.
            organization: The tenant :class:`~app.models.Organization`.
            tracking_uuid: Per-recipient tracking UUID.
            base_url: Application base URL (defaults to settings).
            extra_vars: Overrides (used by tests and previews).

        Returns:
            A mapping of variable name to replacement value.
        """
        base_url = (base_url or self.settings.base_url).rstrip("/")
        uid = str(tracking_uuid)
        department = getattr(employee, "department", None) or "General"
        manager_name = self._resolve_manager_name(employee)

        variables: dict[str, str] = {
            "first_name": getattr(employee, "first_name", "") or "there",
            "last_name": getattr(employee, "last_name", "") or "",
            "email": getattr(employee, "email", "") or "",
            "department": department,
            "company_name": getattr(organization, "name", "") or "Our Company",
            "manager_name": manager_name,
            "job_title": getattr(employee, "job_title", "") or "Employee",
            "tracking_url": f"{base_url}/training/{uid}",
            "tracking_uuid": uid,
            "base_url": base_url,
            "invoice_number": self._generate_invoice_number(),
            "meeting_time": self._generate_meeting_time(),
            "current_year": str(datetime.now(timezone.utc).year),
        }
        if extra_vars:
            variables.update({k: str(v) for k, v in extra_vars.items()})
        return variables

    def personalize(
        self,
        template: Any,
        employee: Any,
        organization: Any,
        tracking_uuid: uuid.UUID | str,
        base_url: str | None = None,
        extra_vars: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Render subject and HTML body for a recipient.

        Every anchor ``href`` is rewritten to the click-tracking endpoint and a
        transparent tracking pixel is appended to the body.

        Args:
            template: The template to render.
            employee: Recipient employee.
            organization: Owning organization.
            tracking_uuid: Per-recipient tracking UUID.
            base_url: Optional base URL override.
            extra_vars: Optional variable overrides.

        Returns:
            ``{"subject": str, "html_content": str}``.
        """
        base_url = (base_url or self.settings.base_url).rstrip("/")
        variables = self.build_variables(
            template, employee, organization, tracking_uuid, base_url, extra_vars
        )

        subject = self._render_text(getattr(template, "subject", "") or "", variables)
        body = self._render_text(getattr(template, "body_html", "") or "", variables)
        body = self.rewrite_links(body, str(tracking_uuid), base_url)
        body = self.append_tracking_pixel(body, str(tracking_uuid), base_url)

        return {"subject": subject, "html_content": body}

    def rewrite_links(self, html: str, tracking_uuid: str, base_url: str) -> str:
        """Wrap every anchor target in the click-tracking redirect.

        Args:
            html: Rendered HTML body.
            tracking_uuid: Per-recipient tracking UUID.
            base_url: Application base URL.

        Returns:
            HTML with rewritten anchors.
        """
        endpoint = f"{base_url}/api/v1/track/click/{tracking_uuid}"

        def _replace(match: re.Match[str]) -> str:
            prefix, quote_char, original = match.group(1), match.group(2), match.group(3)
            if not original or original.strip() in {"#", ""}:
                return match.group(0)
            if "/api/v1/track/click/" in original:
                return match.group(0)
            wrapped = f"{endpoint}?{urlencode({'url': original})}"
            return f"{prefix}{quote_char}{wrapped}{quote_char}"

        return HREF_RE.sub(_replace, html)

    def append_tracking_pixel(self, html: str, tracking_uuid: str, base_url: str) -> str:
        """Append a 1x1 transparent tracking pixel to the body.

        Args:
            html: Rendered HTML body.
            tracking_uuid: Per-recipient tracking UUID.
            base_url: Application base URL.

        Returns:
            HTML with the pixel appended exactly once.
        """
        if "/api/v1/track/open/" in html:
            return html
        pixel = (
            f'<img src="{base_url}/api/v1/track/open/{tracking_uuid}" '
            'width="1" height="1" alt="" '
            'style="display:block;width:1px;height:1px;border:0;outline:none;" />'
        )
        if re.search(r"</body\s*>", html, re.IGNORECASE):
            return re.sub(r"</body\s*>", f"{pixel}</body>", html, count=1, flags=re.IGNORECASE)
        return f"{html}{pixel}"

    def validate_variables(self, template: Any, employee: Any) -> list[str]:
        """List placeholders that cannot be resolved for ``employee``.

        Args:
            template: The template being validated.
            employee: The recipient employee.

        Returns:
            A sorted list of unresolvable variable names (empty when all are
            satisfiable).  ``tracking_url`` is always satisfied because it is
            generated at render time.
        """
        declared = getattr(template, "available_variables", None) or []
        used: set[str] = set()
        for field in (getattr(template, "subject", "") or "", getattr(template, "body_html", "") or ""):
            used.update(VARIABLE_RE.findall(field))

        generated = {
            "tracking_url",
            "tracking_uuid",
            "base_url",
            "invoice_number",
            "meeting_time",
            "current_year",
        }
        employee_values = {
            "first_name": getattr(employee, "first_name", None),
            "last_name": getattr(employee, "last_name", None),
            "email": getattr(employee, "email", None),
            "department": getattr(employee, "department", None),
            "job_title": getattr(employee, "job_title", None),
            "manager_name": self._resolve_manager_name(employee, default=None),
            "company_name": True,  # supplied from the organization
        }

        missing: set[str] = set()
        for name in set(declared) | used:
            if name in generated:
                continue
            value = employee_values.get(name, "__unknown__")
            if value is None or value == "__unknown__":
                missing.add(name)
        return sorted(missing)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _render_text(text: str, variables: dict[str, str], escape: bool = True) -> str:
        """Substitute ``{{var}}`` tokens in ``text``.

        Args:
            text: Source text containing placeholders.
            variables: Name to value mapping.
            escape: When ``True`` values are HTML-escaped before insertion.

        Returns:
            The substituted text with unknown placeholders left intact.
        """

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                return match.group(0)
            value = variables[name]
            return html_lib.escape(value) if escape else value

        return VARIABLE_RE.sub(_replace, text)

    @staticmethod
    def _resolve_manager_name(employee: Any, default: str | None = "Your Manager") -> str | None:
        """Best-effort manager name resolution for an employee.

        Resolution order: an explicit ``manager_name`` attribute, a
        ``manager_name`` key in ``risk_profile``/``behavioral_baseline``, a
        department-derived default, then ``default``.

        Args:
            employee: The recipient employee.
            default: Value returned when nothing is found.

        Returns:
            The manager name or ``default``.
        """
        explicit = getattr(employee, "manager_name", None)
        if explicit:
            return str(explicit)
        for attr in ("risk_profile", "behavioral_baseline", "device_profile"):
            payload = getattr(employee, attr, None)
            if isinstance(payload, dict) and payload.get("manager_name"):
                return str(payload["manager_name"])
        department = getattr(employee, "department", None)
        if department:
            return f"{department} Manager"
        return default

    @staticmethod
    def _generate_invoice_number() -> str:
        """Return a plausible, non-sequential invoice number."""
        return f"INV-{datetime.now(timezone.utc).year}-{secrets.randbelow(9000) + 1000}"

    @staticmethod
    def _generate_meeting_time() -> str:
        """Return a plausible near-future meeting time string."""
        when = datetime.now(timezone.utc) + timedelta(hours=secrets.randbelow(6) + 1)
        return when.strftime("%A, %d %B %Y at %H:%M UTC")


def build_tracking_url(base_url: str, tracking_uuid: str) -> str:
    """Build the canonical training-page URL for a tracking UUID."""
    return f"{base_url.rstrip('/')}/training/{tracking_uuid}"


def build_click_url(base_url: str, tracking_uuid: str, target: str) -> str:
    """Build the click-tracking redirect URL for a target."""
    return f"{base_url.rstrip('/')}/api/v1/track/click/{tracking_uuid}?url={quote(target, safe='')}"
