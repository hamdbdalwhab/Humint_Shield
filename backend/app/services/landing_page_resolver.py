"""Landing-page routing for SMS (smishing) campaigns.

Every SMS recipient gets a short link to ``/sms-lure/{uuid}``.  The skin of
that page is chosen from a landing-page slug (``cisco_vpn``, ``supplier_portal``,
``hr_portal``, ``teams_invite``, ``microsoft_login`` or ``general_login``).

Resolution order (highest priority first):

1. **Department override** — an employee in IT always sees the Cisco VPN
   screen, Finance the supplier portal, HR the policy sign-off and Executive
   the Teams invite.  This keeps a campaign coherent even when the operator
   left the landing page on "auto".
2. **Manual override** — the administrator explicitly picked a page in the
   wizard (``channel_config.sms.selected_landing_page``).
3. **Keyword detection** — the message body is scanned for the vocabulary of
   each scenario (VPN, invoice, policy, meeting, password…).
4. **Default** — ``general_login``.

The resolver is pure: it never touches the database, so it is cheap enough to
run once per recipient inside the launcher.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

#: Every landing page the React ``SmsLureLandingPage`` can render.
LANDING_PAGES: tuple[str, ...] = (
    "cisco_vpn",
    "supplier_portal",
    "hr_portal",
    "teams_invite",
    "microsoft_login",
    "general_login",
)

DEFAULT_LANDING_PAGE = "general_login"

#: Human labels, shared by the wizard and the API.
LANDING_PAGE_LABELS: dict[str, str] = {
    "cisco_vpn": "Cisco AnyConnect — VPN sign-in",
    "supplier_portal": "Supplier Portal — invoice review",
    "hr_portal": "HR Portal — policy sign-off",
    "teams_invite": "Microsoft Teams — meeting invite",
    "microsoft_login": "Microsoft 365 — secure login",
    "general_login": "Generic corporate sign-in",
}

#: ``department -> landing page`` (rule 3, highest priority).
DEPARTMENT_LANDING_PAGES: dict[str, str] = {
    "it": "cisco_vpn",
    "information technology": "cisco_vpn",
    "tech": "cisco_vpn",
    "finance": "supplier_portal",
    "financial": "supplier_portal",
    "accounting": "supplier_portal",
    "hr": "hr_portal",
    "human resources": "hr_portal",
    "people": "hr_portal",
    "executive": "teams_invite",
    "executives": "teams_invite",
    "leadership": "teams_invite",
    "board": "teams_invite",
    "management": "teams_invite",
}

#: Keyword rules (rule 2).  The first matching rule wins, so the order matters:
#: a message that mentions a VPN *and* a password is a VPN lure.
KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cisco_vpn", ("vpn", "anyconnect", "certificate", "network", "firewall", "remote access")),
    ("supplier_portal", ("invoice", "payment", "supplier", "purchase order", "remittance", "wire")),
    ("hr_portal", ("policy", "hr", "sign", "handbook", "acknowledg", "benefits", "payroll")),
    ("teams_invite", ("meeting", "teams", "board", "calendar", "invite", "conference")),
    ("microsoft_login", ("password", "login", "log in", "sign in", "account", "mfa", "2fa", "otp")),
)


def normalize_landing_page(value: Any) -> str | None:
    """Return a supported slug for ``value``, or ``None``.

    Accepts the canonical slug, a label fragment ("Cisco VPN") or a
    case/space variant produced by an older client.
    """
    if value is None:
        return None
    candidate = str(value).strip().lower()
    if not candidate:
        return None
    if candidate in LANDING_PAGES:
        return candidate
    compact = candidate.replace("-", "_").replace(" ", "_")
    if compact in LANDING_PAGES:
        return compact
    aliases = {
        "vpn": "cisco_vpn",
        "cisco": "cisco_vpn",
        "anyconnect": "cisco_vpn",
        "invoice": "supplier_portal",
        "supplier": "supplier_portal",
        "finance": "supplier_portal",
        "hr": "hr_portal",
        "policy": "hr_portal",
        "teams": "teams_invite",
        "meeting": "teams_invite",
        "executive": "teams_invite",
        "microsoft": "microsoft_login",
        "m365": "microsoft_login",
        "office365": "microsoft_login",
        "login": "microsoft_login",
        "general": "general_login",
        "generic": "general_login",
    }
    return aliases.get(compact)


def landing_page_for_department(department: Any) -> str | None:
    """Return the forced landing page for a department, or ``None``."""
    if department is None:
        return None
    value = str(department).strip().lower()
    if not value:
        return None
    if value in DEPARTMENT_LANDING_PAGES:
        return DEPARTMENT_LANDING_PAGES[value]
    for name, page in DEPARTMENT_LANDING_PAGES.items():
        if value.startswith(name):
            return page
    return None


def detect_landing_page(message: str | None) -> str | None:
    """Return the landing page suggested by the message body, or ``None``."""
    text = (message or "").lower()
    if not text.strip():
        return None
    for page, keywords in KEYWORD_RULES:
        if any(keyword in text for keyword in keywords):
            return page
    return None


class LandingPageResolver:
    """Resolve the landing page a recipient's SMS link should open."""

    def resolve(
        self,
        *,
        message: str | None = None,
        department: str | None = None,
        manual: str | None = None,
    ) -> str:
        """Return the landing-page slug for one message/recipient pair.

        Args:
            message: The SMS body (used for keyword detection).
            department: The recipient's department (highest priority).
            manual: The administrator's explicit choice, if any.
        """
        forced = landing_page_for_department(department)
        if forced:
            return forced
        chosen = normalize_landing_page(manual)
        if chosen:
            return chosen
        return detect_landing_page(message) or DEFAULT_LANDING_PAGE

    def resolve_for_config(
        self,
        sms_config: Mapping[str, Any] | None,
        *,
        message: str | None,
        department: str | None = None,
    ) -> str:
        """Resolve from the campaign's ``channel_config.sms`` block."""
        config = dict(sms_config or {})
        return self.resolve(
            message=message,
            department=department,
            manual=config.get("selected_landing_page"),
        )

    @staticmethod
    def suggest(message: str | None, departments: Iterable[str] | None = None) -> dict[str, Any]:
        """Return a suggestion for the wizard's live preview.

        Args:
            message: The draft SMS body.
            departments: The audience's departments (unused reserve).

        Returns:
            ``{"landing_page", "detected", "label"}``.
        """
        detected = detect_landing_page(message)
        page = detected or DEFAULT_LANDING_PAGE
        return {
            "landing_page": page,
            "detected": detected is not None,
            "label": LANDING_PAGE_LABELS.get(page, page),
        }


__all__ = [
    "DEFAULT_LANDING_PAGE",
    "DEPARTMENT_LANDING_PAGES",
    "KEYWORD_RULES",
    "LANDING_PAGES",
    "LANDING_PAGE_LABELS",
    "LandingPageResolver",
    "detect_landing_page",
    "landing_page_for_department",
    "normalize_landing_page",
]
