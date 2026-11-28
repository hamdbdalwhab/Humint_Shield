"""Seed data: built-in templates, bootstrap org/admin and LMS catalogue.

The built-in templates are written to look like genuine business email (that is
the point of a simulation) while every template routes through the tracking URL
so engagement is measurable and the landing page immediately discloses that the
message was an authorized training exercise.
"""
from __future__ import annotations

import html
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.services.email_design import legacy_design_payload
from app.models import (
    EmailTemplate,
    HumanAsset,
    Organization,
    TrainingModule,
    User,
)
from app.security import hash_password

logger = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Shared HTML chrome
# --------------------------------------------------------------------------- #
#: Signature of the pre-redesign wrapper.  Built-in templates that still carry
#: it are upgraded in place on startup; templates an administrator edited are
#: never touched.
LEGACY_WRAPPER_MARKER = "font-family:Arial,Helvetica,sans-serif;font-size:14px"


def _details(rows: list[tuple[str, str]]) -> str:
    """Render a two-column detail table that survives Outlook and Gmail."""
    cells = "".join(
        "<tr>"
        '<td style="padding:9px 0;border-bottom:1px solid #f2f4f7;font-size:13px;'
        f'color:#667085;width:38%;">{label}</td>'
        '<td style="padding:9px 0;border-bottom:1px solid #f2f4f7;font-size:13px;'
        f'color:#101828;font-weight:600;">{value}</td>'
        "</tr>"
        for label, value in rows
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="margin:20px 0 24px;">'
        f"{cells}</table>"
    )


def _callout(text: str, *, tone: str = "info") -> str:
    """Render a coloured callout box."""
    palette = {
        "info": ("#0f6cbd", "#eff6ff"),
        "warning": ("#b54708", "#fffaeb"),
        "danger": ("#b42318", "#fef3f2"),
        "success": ("#067647", "#ecfdf3"),
    }
    border, background = palette.get(tone, palette["info"])
    return (
        f'<div style="margin:20px 0;padding:14px 16px;border-left:4px solid {border};'
        f'background:{background};border-radius:6px;font-size:14px;line-height:1.6;'
        f'color:#344054;">{text}</div>'
    )


def _heading(text: str) -> str:
    """Return a consistent page heading."""
    return (
        '<h1 style="margin:0 0 14px;font-family:\'Segoe UI\',Roboto,Helvetica,Arial,'
        'sans-serif;font-size:22px;line-height:1.3;font-weight:700;color:#101828;">'
        f"{text}</h1>"
    )


def _button(label: str) -> str:
    """Return an email-safe call-to-action button."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:26px 0;"><tr>'
        '<td style="border-radius:8px;background:#0f6cbd;">'
        '<a href="{{tracking_url}}" style="display:inline-block;padding:13px 26px;'
        "font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;"
        'font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px;">'
        f"{label}</a></td></tr></table>"
    )


def _email_shell(body: str) -> str:
    """Wrap body content in the branded, table-based email shell."""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width,initial-scale=1" />'
        "<title>{{company_name}}</title></head>"
        '<body style="margin:0;padding:0;background:#f2f4f7;">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
        "You have a new service message from {{company_name}}.</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="background:#f2f4f7;padding:28px 12px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'border="0" style="width:600px;max-width:600px;background:#ffffff;'
        'border:1px solid #e4e7ec;border-radius:14px;overflow:hidden;'
        "font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;\">"
        '<tr><td style="height:4px;background:#0f6cbd;font-size:0;line-height:0;">'
        "&nbsp;</td></tr>"
        '<tr><td style="padding:20px 32px;border-bottom:1px solid #eaecf0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="width:38px;">'
        '<div style="width:36px;height:36px;border-radius:10px;background:#0b4f8a;'
        'color:#ffffff;font-size:13px;font-weight:700;text-align:center;line-height:36px;'
        'letter-spacing:.5px;">IT</div></td>'
        '<td style="padding-left:12px;">'
        '<div style="font-size:15px;font-weight:700;color:#101828;">{{company_name}}</div>'
        '<div style="font-size:10px;color:#667085;text-transform:uppercase;'
        'letter-spacing:1.1px;">Employee Services</div>'
        "</td></tr></table></td></tr>"
        '<tr><td style="padding:32px 32px 8px 32px;font-size:15px;line-height:1.65;'
        f'color:#344054;">{body}</td></tr>'
        '<tr><td style="padding:4px 32px 28px 32px;">'
        '<div style="border-top:1px solid #eaecf0;padding-top:18px;font-size:12px;'
        'line-height:1.7;color:#98a2b3;">'
        'This service message was sent to <strong style="color:#667085;">{{email}}</strong> '
        "because you hold an account at {{company_name}}.<br />"
        "If you were not expecting it, contact the IT service desk.<br /><br />"
        "&copy; {{current_year}} {{company_name}}. All rights reserved."
        "</div></td></tr>"
        "</table>"
        '<div style="max-width:600px;padding:14px 8px 0;font-size:11px;line-height:1.5;'
        'color:#98a2b3;text-align:center;">Please do not reply to this automated message.</div>'
        "</td></tr></table></body></html>"
    )


def _template(
    name: str,
    subject: str,
    body: str,
    difficulty: int,
    variables: list[str],
    channel: str = "email",
) -> dict[str, Any]:
    """Assemble a built-in template definition."""
    return {
        "name": name,
        "subject": subject,
        "body_html": _email_shell(body),
        "difficulty_level": difficulty,
        "available_variables": variables,
        "channel": channel,
    }


# --------------------------------------------------------------------------- #
# High-fidelity "hook" templates
# --------------------------------------------------------------------------- #
# These five templates intentionally reproduce the visual language of the
# services employees use every day. Every link resolves to the tracking
# endpoint and the landing page discloses the simulation immediately.
def _ms365_template() -> dict[str, Any]:
    """Return the Microsoft 365 password-expiry simulation."""
    body = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Microsoft 365</title></head>
<body style="margin:0;padding:0;background:#f3f2f1;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">Your Microsoft 365 password expires today.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f2f1;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#ffffff;border:1px solid #e1dfdd;border-radius:4px;font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif;">
<tr><td style="padding:26px 32px 18px 32px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="width:26px;vertical-align:middle;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:20px;height:20px;"><tr>
        <td style="width:10px;height:10px;background:#f25022;"></td><td style="width:10px;height:10px;background:#7fba00;"></td>
      </tr><tr>
        <td style="width:10px;height:10px;background:#00a4ef;"></td><td style="width:10px;height:10px;background:#ffb900;"></td>
      </tr></table>
    </td>
    <td style="padding-left:9px;font-size:15px;font-weight:600;color:#242424;">Microsoft 365</td>
  </tr></table>
</td></tr>
<tr><td style="padding:0 32px 28px 32px;color:#242424;font-size:14px;line-height:1.65;">
  <h1 style="margin:10px 0 16px;font-size:24px;line-height:1.3;font-weight:600;color:#242424;">Your password expires today</h1>
  <p style="margin:0 0 14px;">Hi {{first_name}},</p>
  <p style="margin:0 0 18px;">The password for your <strong>{{company_name}}</strong> work account no longer meets the current security policy and will expire at <strong>11:59 PM today</strong>.</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #edebe9;border-radius:4px;margin:0 0 20px;">
    <tr><td style="padding:14px 16px;font-size:13px;line-height:1.7;color:#424242;">
      <div><span style="color:#605e5c;">Account:</span> <strong>{{email}}</strong></div>
      <div><span style="color:#605e5c;">Policy:</span> Minimum 14 characters, no reuse</div>
      <div><span style="color:#605e5c;">Deadline:</span> Today, 11:59 PM</div>
      <div><span style="color:#605e5c;">Reference:</span> SEC-{{current_year}}-4471</div>
    </td></tr>
  </table>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;"><tr>
    <td style="border-radius:4px;background:#0078d4;">
      <a href="{{tracking_url}}" style="display:inline-block;padding:12px 26px;font-family:'Segoe UI',Arial,sans-serif;font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:4px;">Change password now</a>
    </td>
  </tr></table>
  <p style="margin:0 0 12px;color:#605e5c;font-size:13px;">If you do not update your password, your mailbox will be switched to read-only and you will be signed out of all devices.</p>
  <p style="margin:0;">Thanks,<br /><strong>IT Service Desk</strong><br />{{company_name}}</p>
</td></tr>
<tr><td style="padding:18px 32px;border-top:1px solid #edebe9;font-size:11px;line-height:1.7;color:#8a8886;">
  This message was sent to {{email}} because you have a Microsoft 365 account at {{company_name}}.<br />
  Microsoft Corporation · One Microsoft Way · Redmond, WA 98052
</td></tr>
</table>
</td></tr></table></body></html>"""
    return {
        "name": "Microsoft 365 · Password Expiring",
        "subject": "Action required: Your Microsoft 365 password expires today",
        "body_html": body,
        "difficulty_level": 4,
        "available_variables": ["first_name", "email", "company_name", "current_year", "tracking_url"],
    }


def _hr_portal_template() -> dict[str, Any]:
    """Return the formal HR records-review simulation."""
    body = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>HR Portal</title></head>
<body style="margin:0;padding:0;background:#eef1f5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef1f5;padding:34px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#ffffff;border-top:5px solid #12324f;font-family:Arial,Helvetica,sans-serif;">
<tr><td style="padding:24px 34px;border-bottom:1px solid #e3e8ee;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="width:42px;height:42px;background:#12324f;color:#ffffff;text-align:center;line-height:42px;font-size:16px;font-weight:700;">{{company_name}}</td>
    <td style="padding-left:13px;">
      <div style="font-size:16px;font-weight:700;color:#12324f;">Human Resources</div>
      <div style="font-size:10px;letter-spacing:1.4px;color:#7b8794;text-transform:uppercase;">Employee Records Portal</div>
    </td>
  </tr></table>
</td></tr>
<tr><td style="padding:32px 34px 10px;color:#243b53;font-size:15px;line-height:1.7;">
  <div style="display:inline-block;padding:5px 11px;background:#fff4e5;border:1px solid #ffd7a8;border-radius:99px;font-size:11px;font-weight:700;color:#9a5b00;letter-spacing:.4px;">ACTION REQUIRED</div>
  <h1 style="margin:16px 0 12px;font-size:24px;font-weight:700;color:#12324f;">Update your employee records</h1>
  <p style="margin:0 0 16px;">Dear {{first_name}},</p>
  <p style="margin:0 0 16px;">As part of the annual compliance review, every employee must confirm their personal and payroll information before <strong>Friday, 5:00 PM</strong>.</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f7f9fc;border:1px solid #e3e8ee;padding:6px 18px;margin:0 0 22px;">
    <tr><td style="padding:12px 0;border-bottom:1px solid #e3e8ee;font-size:13px;color:#486581;">Home address and emergency contact</td></tr>
    <tr><td style="padding:12px 0;border-bottom:1px solid #e3e8ee;font-size:13px;color:#486581;">Bank account and payroll details</td></tr>
    <tr><td style="padding:12px 0;font-size:13px;color:#486581;">Tax residency declaration</td></tr>
  </table>
  <p style="margin:0 0 22px;">Unconfirmed records may delay payroll processing for the current cycle.</p>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px;"><tr>
    <td style="background:#12324f;border-radius:5px;"><a href="{{tracking_url}}" style="display:inline-block;padding:14px 30px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;">Open employee portal</a></td>
  </tr></table>
  <p style="margin:0;">Kind regards,<br /><strong>Human Resources Department</strong><br />{{company_name}}</p>
</td></tr>
<tr><td style="padding:18px 34px;background:#f7f9fc;border-top:1px solid #e3e8ee;font-size:11px;line-height:1.6;color:#829ab1;">
  This is a confidential HR communication intended for {{email}}. If you received it in error, please delete it.
</td></tr>
</table>
</td></tr></table></body></html>"""
    return {
        "name": "HR Portal · Employee Records Review",
        "subject": "Action required: Update your employee information",
        "body_html": body,
        "difficulty_level": 4,
        "available_variables": ["first_name", "email", "company_name", "tracking_url"],
    }


def _ceo_template() -> dict[str, Any]:
    """Return the short, direct CEO-message simulation."""
    body = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Message from the CEO</title></head>
<body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;padding:40px 16px;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:560px;max-width:560px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
<tr><td style="padding:0 0 22px;border-bottom:1px solid #eaeaea;">
  <div style="font-size:15px;font-weight:700;color:#111111;">{{company_name}}</div>
  <div style="font-size:11px;color:#888888;letter-spacing:.5px;">OFFICE OF THE CHIEF EXECUTIVE</div>
</td></tr>
<tr><td style="padding:28px 0 0;color:#222222;font-size:15px;line-height:1.75;">
  <p style="margin:0 0 16px;">{{first_name}},</p>
  <p style="margin:0 0 16px;">I need five minutes of your attention before the board briefing today.</p>
  <p style="margin:0 0 16px;">Review the confidential note I shared. It covers the acquisition timeline and the two names we discussed. Please do not forward it.</p>
  <p style="margin:0 0 24px;">
    <a href="{{tracking_url}}" style="display:inline-block;padding:12px 22px;background:#111111;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;border-radius:3px;">Open secure brief</a>
  </p>
  <p style="margin:0 0 6px;">Thanks,</p>
  <p style="margin:0;font-weight:700;">Sent from my iPhone</p>
</td></tr>
<tr><td style="padding:26px 0 0;border-top:1px solid #eaeaea;margin-top:30px;font-size:10px;color:#999999;line-height:1.6;">
  This message and any attachments are confidential and intended solely for {{email}}.
</td></tr>
</table>
</td></tr></table></body></html>"""
    return {
        "name": "CEO Message · Urgent Brief",
        "subject": "Urgent action required — before today's board briefing",
        "body_html": body,
        "difficulty_level": 7,
        "available_variables": ["first_name", "email", "company_name", "tracking_url"],
    }


def _vendor_invoice_template() -> dict[str, Any]:
    """Return the vendor invoice simulation with a realistic line-item table."""
    body = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Invoice</title></head>
<body style="margin:0;padding:0;background:#f4f5f7;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f5f7;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="620" cellpadding="0" cellspacing="0" border="0" style="width:620px;max-width:620px;background:#ffffff;border:1px solid #dfe3e8;font-family:Arial,Helvetica,sans-serif;">
<tr><td style="padding:28px 34px;background:#0d2137;color:#ffffff;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td><div style="font-size:18px;font-weight:700;letter-spacing:.5px;">NORTHSTAR SUPPLY</div>
    <div style="font-size:10px;color:#8fb3d9;letter-spacing:1.5px;">PROCUREMENT &amp; LOGISTICS</div></td>
    <td align="right"><div style="font-size:26px;font-weight:700;color:#ffffff;">INVOICE</div>
    <div style="font-size:12px;color:#8fb3d9;">{{invoice_number}}</div></td>
  </tr></table>
</td></tr>
<tr><td style="padding:26px 34px;color:#243b53;font-size:14px;line-height:1.65;">
  <p style="margin:0 0 6px;"><strong>Bill to:</strong> {{company_name}}</p>
  <p style="margin:0 0 4px;color:#627d98;">Attn: {{first_name}} · {{email}}</p>
  <p style="margin:0 0 22px;color:#627d98;">Issue date: Today &nbsp;·&nbsp; Due date: Net 30</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;">
    <tr style="background:#f0f4f8;">
      <th align="left" style="padding:10px 12px;border-bottom:1px solid #d9e2ec;color:#486581;font-size:11px;letter-spacing:.4px;">DESCRIPTION</th>
      <th align="center" style="padding:10px 12px;border-bottom:1px solid #d9e2ec;color:#486581;font-size:11px;">QTY</th>
      <th align="right" style="padding:10px 12px;border-bottom:1px solid #d9e2ec;color:#486581;font-size:11px;">AMOUNT</th>
    </tr>
    <tr><td style="padding:12px;border-bottom:1px solid #edf1f5;">Enterprise network hardware — batch 04</td><td align="center" style="padding:12px;border-bottom:1px solid #edf1f5;">12</td><td align="right" style="padding:12px;border-bottom:1px solid #edf1f5;">$11,940.00</td></tr>
    <tr><td style="padding:12px;border-bottom:1px solid #edf1f5;">Managed switch licensing (annual)</td><td align="center" style="padding:12px;border-bottom:1px solid #edf1f5;">1</td><td align="right" style="padding:12px;border-bottom:1px solid #edf1f5;">$4,800.00</td></tr>
    <tr><td style="padding:12px;border-bottom:1px solid #edf1f5;">On-site installation &amp; configuration</td><td align="center" style="padding:12px;border-bottom:1px solid #edf1f5;">1</td><td align="right" style="padding:12px;border-bottom:1px solid #edf1f5;">$1,680.00</td></tr>
    <tr><td colspan="2" align="right" style="padding:14px 12px;font-weight:700;color:#486581;">TOTAL DUE</td><td align="right" style="padding:14px 12px;font-weight:700;font-size:16px;color:#0d2137;">$18,420.00</td></tr>
  </table>
  <div style="margin:22px 0;padding:12px 14px;background:#fff8e6;border-left:4px solid #f0b429;font-size:12px;color:#7a5200;line-height:1.6;">Payment is now 5 days overdue. A late-payment fee may be applied if the balance is not settled within 48 hours.</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="background:#0d2137;border-radius:4px;"><a href="{{tracking_url}}" style="display:inline-block;padding:13px 26px;color:#ffffff;font-size:14px;font-weight:700;text-decoration:none;">Review invoice</a></td>
  </tr></table>
</td></tr>
<tr><td style="padding:16px 34px;background:#f0f4f8;border-top:1px solid #d9e2ec;font-size:10px;color:#829ab1;line-height:1.6;">
  Northstar Supply Ltd · 18 Harbour Exchange · London E14 9GE · VAT GB 884 221 907<br />
  Questions? Reply to billing@northstar-supply.example
</td></tr>
</table>
</td></tr></table></body></html>"""
    return {
        "name": "Vendor Invoice · Overdue Balance",
        "subject": "Invoice {{invoice_number}} is overdue — immediate review required",
        "body_html": body,
        "difficulty_level": 6,
        "available_variables": ["first_name", "email", "company_name", "invoice_number", "tracking_url"],
    }


def _gdrive_template() -> dict[str, Any]:
    """Return the Google Drive shared-document simulation."""
    body = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>A document has been shared with you</title></head>
<body style="margin:0;padding:0;background:#f1f3f4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f3f4;padding:30px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#ffffff;border-radius:10px;border:1px solid #dadce0;font-family:'Google Sans',Roboto,Arial,sans-serif;">
<tr><td style="padding:22px 30px 14px;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="width:30px;vertical-align:middle;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:26px;height:24px;"><tr>
        <td style="width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-bottom:14px solid #0f9d58;"></td>
        <td style="width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-bottom:14px solid #f4b400;margin-left:-8px;"></td>
      </tr></table>
    </td>
    <td style="padding-left:10px;font-size:14px;color:#5f6368;font-weight:500;">Google Drive</td>
  </tr></table>
</td></tr>
<tr><td style="padding:14px 30px 8px;color:#202124;">
  <h1 style="margin:0 0 8px;font-size:23px;line-height:1.35;font-weight:500;">A document has been shared with you</h1>
  <p style="margin:0;color:#5f6368;font-size:13px;">{{first_name}}, a file was shared by a colleague at {{company_name}}.</p>
</td></tr>
<tr><td style="padding:22px 30px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #dadce0;border-radius:8px;">
    <tr><td style="padding:16px 18px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="width:44px;vertical-align:top;">
          <div style="width:38px;height:44px;border:1px solid #dadce0;border-radius:4px;background:#f8f9fa;text-align:center;padding-top:12px;font-size:10px;font-weight:700;color:#d93025;">PPTX</div>
        </td>
        <td style="padding-left:12px;">
          <div style="font-size:14px;font-weight:600;color:#202124;">Q4 strategy review — final.pptx</div>
          <div style="font-size:12px;color:#5f6368;margin-top:2px;">Shared by: {{manager_name}} · 4.8 MB</div>
          <div style="font-size:12px;color:#5f6368;">You have comment access</div>
        </td>
      </tr></table>
    </td></tr>
  </table>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 10px;"><tr>
    <td style="border-radius:6px;background:#1a73e8;"><a href="{{tracking_url}}" style="display:inline-block;padding:13px 30px;font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:6px;">Open document</a></td>
  </tr></table>
  <p style="margin:0;font-size:11px;color:#80868b;line-height:1.6;">Google Drive · This notification was sent to {{email}} because a document was shared with you.</p>
</td></tr>
</table>
</td></tr></table></body></html>"""
    return {
        "name": "Google Drive · Shared Document",
        "subject": "A document has been shared with you: Q4 strategy review — final.pptx",
        "body_html": body,
        "difficulty_level": 5,
        "available_variables": ["first_name", "email", "company_name", "manager_name", "tracking_url"],
    }


BUILT_IN_TEMPLATES: list[dict[str, Any]] = [
    _template(
        name="Urgent Password Change",
        subject="Urgent: Your password must be changed within 24 hours",
        difficulty=3,
        variables=["first_name", "email", "company_name", "current_year", "tracking_url"],
        body=(
            _heading("Your password expires today")
            + "<p>Dear {{first_name}},</p>"
            "<p>Our identity service detected that the password for your "
            "<strong>{{company_name}}</strong> account no longer meets the current "
            "security policy and will expire at the end of the day.</p>"
            + _details(
                [
                    ("Account", "{{email}}"),
                    ("Policy", "Minimum 14 characters, no reuse"),
                    ("Action deadline", "Today, 23:59"),
                    ("Reference", "SEC-{{current_year}}-4471"),
                ]
            )
            + _callout(
                "<strong>Action required.</strong> If the password is not updated, your "
                "mailbox will be switched to read-only and you will be signed out of all "
                "devices.",
                tone="warning",
            )
            + "<p>Choose a new password to keep access to email, Teams and SharePoint.</p>"
            + _button("Change password now")
            + "<p>If you have already changed your password, you can ignore this message.</p>"
            "<p>Regards,<br /><strong>IT Service Desk</strong><br />{{company_name}}</p>"
        ),
    ),
    _template(
        name="Message from Direct Manager",
        subject="Please review this document before our meeting",
        difficulty=6,
        variables=[
            "first_name",
            "email",
            "department",
            "manager_name",
            "company_name",
            "current_year",
            "tracking_url",
        ],
        body=(
            _heading("A document has been shared with you")
            + "<p>Hi {{first_name}},</p>"
            "<p>I have shared the updated <strong>{{department}}</strong> planning "
            "document and I need your comments before our catch-up.</p>"
            + _details(
                [
                    ("Shared by", "{{manager_name}}"),
                    ("Document", "{{department}} planning — final draft"),
                    ("Access", "Comment only"),
                    ("Expires", "In 7 days"),
                ]
            )
            + _callout(
                "Please review the figures on page 4 before we meet. I have flagged the "
                "two sections that changed.",
                tone="info",
            )
            + _button("Open the document")
            + "<p>Thanks,<br /><strong>{{manager_name}}</strong></p>"
        ),
    ),
    _template(
        name="Suspicious Login Alert",
        subject="Security Alert: Unusual login detected on your account",
        difficulty=4,
        variables=[
            "first_name",
            "email",
            "company_name",
            "current_year",
            "tracking_url",
        ],
        body=(
            _heading("New sign-in to your account")
            + "<p>Hello {{first_name}},</p>"
            "<p>We detected a sign-in to your <strong>{{company_name}}</strong> account "
            "from a device we do not recognise.</p>"
            + _details(
                [
                    ("Location", "Amsterdam, Netherlands"),
                    ("Device", "Windows 11 · Chrome 131"),
                    ("Time", "Today, 02:14 (UTC)"),
                    ("IP address", "185.220.101.42"),
                ]
            )
            + _callout(
                "If this was you, no action is needed. If not, secure your account "
                "immediately.",
                tone="danger",
            )
            + _button("Review activity and secure account")
            + "<p>Security Operations · {{company_name}}</p>"
        ),
    ),
    _template(
        name="HR Data Update Required",
        subject="Action Required: Update your employee information",
        difficulty=5,
        variables=["first_name", "email", "company_name", "current_year", "tracking_url"],
        body=(
            _heading("Annual employee records review")
            + "<p>Dear {{first_name}},</p>"
            "<p>As part of the {{company_name}} annual records review, every employee "
            "must confirm their personal and payroll details.</p>"
            "<ul style=\"margin:16px 0;padding-left:22px;\">"
            "<li>Home address and emergency contact</li>"
            "<li>Bank account for payroll</li>"
            "<li>Tax residency declaration</li>"
            "</ul>"
            + _callout(
                "Please complete the form within <strong>3 working days</strong>. "
                "Unconfirmed records can delay payroll processing.",
                tone="warning",
            )
            + _button("Update my information")
            + "<p>Kind regards,<br /><strong>HR Department</strong><br />{{company_name}}</p>"
        ),
    ),
    _template(
        name="Overdue Invoice",
        subject="Invoice overdue — Immediate review required",
        difficulty=7,
        variables=[
            "first_name",
            "email",
            "company_name",
            "invoice_number",
            "current_year",
            "tracking_url",
        ],
        body=(
            _heading("Invoice overdue — payment required")
            + "<p>Dear {{first_name}},</p>"
            "<p>Our records show that the invoice below remains unpaid and is now past "
            "due.</p>"
            + _details(
                [
                    ("Invoice number", "{{invoice_number}}"),
                    ("Account", "{{company_name}}"),
                    ("Amount due", "$18,420.00"),
                    ("Due date", "5 days ago"),
                ]
            )
            + _callout(
                "A late-payment fee may be applied if the balance is not settled within "
                "48 hours.",
                tone="danger",
            )
            + _button("Review invoice {{invoice_number}}")
            + "<p>Finance Department<br />{{company_name}}</p>"
        ),
    ),
    _template(
        name="Employee Bonus Announcement",
        subject="Congratulations! You've been selected for a performance bonus",
        difficulty=8,
        variables=["first_name", "email", "company_name", "current_year", "tracking_url"],
        body=(
            _heading("Your performance bonus is ready")
            + "<p>Dear {{first_name}},</p>"
            "<p>Following the {{company_name}} performance review, you have been "
            "selected for a discretionary bonus this quarter.</p>"
            + _details(
                [
                    ("Award", "Quarterly performance bonus"),
                    ("Amount", "$2,500.00 gross"),
                    ("Payment date", "This Friday"),
                    ("Status", "Awaiting bank confirmation"),
                ]
            )
            + _callout(
                "Confirm your bank details before Friday to release the payment.",
                tone="success",
            )
            + _button("Claim my bonus")
            + "<p>HR Director · {{company_name}}</p>"
        ),
    ),
    _template(
        name="Emergency Meeting Notice",
        subject="Emergency meeting — Your presence is required",
        difficulty=5,
        variables=[
            "first_name",
            "email",
            "company_name",
            "meeting_time",
            "current_year",
            "tracking_url",
        ],
        body=(
            _heading("Emergency meeting — attendance required")
            + "<p>{{first_name}},</p>"
            "<p>An emergency leadership meeting has been scheduled. Your presence is "
            "required.</p>"
            + _details(
                [
                    ("When", "{{meeting_time}}"),
                    ("Where", "Executive boardroom / Teams"),
                    ("Agenda", "Incident briefing and next steps"),
                    ("Dial-in", "Included in the briefing pack"),
                ]
            )
            + _button("Confirm attendance and open briefing")
            + "<p>Executive Assistant<br />{{company_name}}</p>"
        ),
    ),
    _template(
        name="Mandatory Software Update",
        subject="Mandatory security update for your device",
        difficulty=4,
        variables=["first_name", "email", "company_name", "current_year", "tracking_url"],
        body=(
            _heading("Critical security update required")
            + "<p>Hello {{first_name}},</p>"
            "<p>A critical security update is ready for your {{company_name}} "
            "workstation and must be installed today.</p>"
            + _details(
                [
                    ("Update", "Endpoint Security 7.4.2"),
                    ("Size", "84 MB"),
                    ("Deadline", "Today, 18:00"),
                    ("Restart", "Required"),
                ]
            )
            + _callout(
                "Devices that are not updated will be disconnected from the corporate "
                "network at the end of the day.",
                tone="warning",
            )
            + _button("Install the update now")
            + "<p>IT Department · {{company_name}}</p>"
        ),
    ),
    # ------------------------------------------------------------------ #
    # Built-in QR/quishing lure templates.  Each one is a printable poster
    # scenario; the campaign wizard filters templates by channel = 'qr'.
    # ------------------------------------------------------------------ #
    _template(
        name="قهوة مجانية",
        subject="قهوة مجانية بانتظارك اليوم",
        difficulty=3,
        variables=["company_name", "department"],
        channel="qr",
        body=(
            _heading("قهوة مجانية بانتظارك اليوم")
            + "<p>بمناسبة أسبوع الامتنان، تقدّم كافتيريا الشركة مشروباً ساخناً مجاناً "
            "لكل موظف. امسح رمز QR الموجود على الملصق لاستلام قسيمتك قبل الساعة "
            "الثالثة عصراً.</p>"
        ),
    ),
    _template(
        name="مكافأة مالية",
        subject="تم اعتماد مكافأة الأداء",
        difficulty=5,
        variables=["company_name", "department"],
        channel="qr",
        body=(
            _heading("تم اعتماد مكافأة الأداء")
            + "<p>يسر الإدارة المالية إبلاغك باعتماد مكافأة الأداء لهذا الربع. امسح رمز "
            "QR للتحقق من بياناتك وتأكيد استلام المكافأة قبل إغلاق دورة الرواتب.</p>"
        ),
    ),
    _template(
        name="ترشيح لأفضل موظف",
        subject="ترشيحك لأفضل موظف هذا الشهر",
        difficulty=4,
        variables=["company_name", "department"],
        channel="qr",
        body=(
            _heading("ترشيحك لأفضل موظف")
            + "<p>تم ترشيحك ضمن قائمة أفضل الموظفين لهذا الشهر. امسح رمز QR للاطلاع "
            "على تفاصيل الترشيح وتأكيد قبولك قبل إعلان النتائج.</p>"
        ),
    ),
    _template(
        name="تحديث بيانات HR",
        subject="تحديث بيانات الموظف مطلوب",
        difficulty=4,
        variables=["company_name", "department"],
        channel="qr",
        body=(
            _heading("تحديث بيانات الموظف مطلوب")
            + "<p>يتطلب نظام الموارد البشرية تحديث بياناتك الشخصية وبيانات الاتصال. "
            "امسح رمز QR لإكمال التحديث قبل نهاية الأسبوع لتجنّب تعليق الخدمات.</p>"
        ),
    ),
    _template(
        name="شبكة الواي فاي",
        subject="دخول سريع إلى شبكة الشركة",
        difficulty=3,
        variables=["company_name", "department"],
        channel="qr",
        body=(
            _heading("دخول سريع إلى شبكة الشركة")
            + "<p>شبكة Wi-Fi للزوار تتطلب تسجيل الدخول مرة واحدة على الأجهزة الجديدة. "
            "امسح رمز QR لتفعيل الاتصال بالإنترنت داخل مبنى الإدارة.</p>"
        ),
    ),
    _ms365_template(),
    _hr_portal_template(),
    _ceo_template(),
    _vendor_invoice_template(),
    _gdrive_template(),
]

DEMO_TRAINING_MODULES: list[dict[str, Any]] = [
    {
        "title": "Spotting Phishing Emails",
        "summary": "Recognise the classic red flags of a phishing attempt.",
        "category": "Email Security",
        "duration_minutes": 10,
        "difficulty_level": 2,
        "content_html": (
            "<h3>Spotting Phishing Emails</h3>"
            "<p>Phishing relies on urgency, authority and a plausible pretext. Before you "
            "click, check the sender domain, hover the link, and ask yourself whether the "
            "request makes sense.</p>"
            "<ul><li>Is the sender domain exactly right?</li>"
            "<li>Is there manufactured urgency?</li>"
            "<li>Does the link destination match the visible text?</li>"
            "<li>Are you being asked for credentials or payment details?</li></ul>"
        ),
    },
    {
        "title": "Password Hygiene & MFA",
        "summary": "Strong, unique passwords and why MFA matters.",
        "category": "Credentials",
        "duration_minutes": 8,
        "difficulty_level": 1,
        "content_html": (
            "<h3>Password Hygiene &amp; MFA</h3>"
            "<p>Use a password manager, never reuse passwords, and enable multi-factor "
            "authentication everywhere it is offered. No service will ever ask you for your "
            "password by email.</p>"
        ),
    },
    {
        "title": "Handling Sensitive Data",
        "summary": "Classify, store and share personal data safely.",
        "category": "Data Protection",
        "duration_minutes": 12,
        "difficulty_level": 3,
        "content_html": (
            "<h3>Handling Sensitive Data</h3>"
            "<p>Personal and financial data must be classified before it is shared, stored "
            "only where approved, and transferred over encrypted channels.</p>"
        ),
    },
    {
        "title": "Business Email Compromise",
        "summary": "Detect invoice fraud and executive impersonation.",
        "category": "Email Security",
        "duration_minutes": 14,
        "difficulty_level": 4,
        "content_html": (
            "<h3>Business Email Compromise</h3>"
            "<p>BEC attacks impersonate executives or suppliers to redirect payments. Always "
            "verify new payment instructions out-of-band using a known-good phone number.</p>"
        ),
    },
]


# --------------------------------------------------------------------------- #
# Built-in SMS (smishing) templates
# --------------------------------------------------------------------------- #
# SMS bodies are plain text: the personaliser converts the stored HTML to text
# and the launcher appends the dedicated ``/api/v1/track/sms/{uuid}`` link.
def _sms_template(
    name: str,
    text: str,
    difficulty: int,
    variables: list[str],
    target_department: str = "All",
) -> dict[str, Any]:
    """Assemble a built-in SMS template definition.

    Args:
        name: Display name in the campaign wizard.
        text: Plain-text body (``{{link}}`` is the short-link placeholder).
        difficulty: 1-10 difficulty level.
        variables: Merge tags the template uses.
        target_department: ``IT``, ``Finance``, ``HR``, ``Executive`` or ``All``.
    """
    return {
        "name": name,
        "subject": name,
        "body_html": f"<p>{html.escape(text)}</p>",
        "difficulty_level": difficulty,
        "available_variables": variables,
        "channel": "sms",
        "target_department": target_department,
    }


#: High-fidelity smishing lures. Bodies are plain text, contain no simulation
#: wording, and use ``{{link}}`` (resolved to the per-recipient SMS tracker).
SMS_TEMPLATE_DEFINITIONS: list[dict[str, Any]] = [
    _sms_template(
        name="IT Security Alert",
        text=(
            "Dear {{first_name}}, our system detected an unauthorized login "
            "attempt on your {{company_name}} account from a new device. To "
            "secure your account, please verify your identity immediately: "
            "{{link}}"
        ),
        difficulty=3,
        variables=["first_name", "company_name", "link"],
    ),
    _sms_template(
        name="HR Bonus Approval",
        text=(
            "Congratulations {{first_name}}! Your performance bonus for this "
            "quarter has been approved. Please review the breakdown and confirm "
            "your bank details here: {{link}}"
        ),
        difficulty=4,
        variables=["first_name", "link"],
    ),
    _sms_template(
        name="Courier Delivery Notice",
        text=(
            "{{company_name}} Delivery: Your package is on hold at our local "
            "facility due to incomplete address details. Please update your "
            "shipping information within 24 hours to avoid return: {{link}}"
        ),
        difficulty=2,
        variables=["company_name", "link"],
    ),
    _sms_template(
        name="Executive Quick Request",
        text=(
            "Hi {{first_name}}, I am in a meeting and need a quick favor. Are "
            "you available? Please click here to view the urgent request: "
            "{{link}}"
        ),
        difficulty=5,
        variables=["first_name", "link"],
    ),
    _sms_template(
        name="VPN Certificate Expiry",
        text=(
            "{{first_name}}, your VPN certificate expires today. Failure to "
            "renew will result in loss of remote access. Renew now: {{link}}"
        ),
        difficulty=3,
        variables=["first_name", "link"],
    ),
    # Department-aware lures (<=170 characters including the link placeholder).
    _sms_template(
        name="IT · VPN Session Expiry",
        text="Your VPN session expires today. Re-authenticate here: {{link}}",
        difficulty=3,
        variables=["link"],
        target_department="IT",
    ),
    _sms_template(
        name="Finance · Invoice Pending Approval",
        text=(
            "Invoice #{{invoice_id}} is pending approval. Review here: "
            "{{link}}"
        ),
        difficulty=4,
        variables=["invoice_id", "link"],
        target_department="Finance",
    ),
    _sms_template(
        name="HR · Policy Sign-off",
        text="Mandatory policy update. Please sign here: {{link}}",
        difficulty=3,
        variables=["link"],
        target_department="HR",
    ),
    _sms_template(
        name="Executive · Board Meeting Change",
        text="Urgent: Board meeting moved. Join here: {{link}}",
        difficulty=5,
        variables=["link"],
        target_department="Executive",
    ),
]

#: Built-in SMS templates are seeded alongside the email set.
BUILT_IN_TEMPLATES.extend(SMS_TEMPLATE_DEFINITIONS)


# --------------------------------------------------------------------------- #
# Built-in WhatsApp templates
# --------------------------------------------------------------------------- #
# WhatsApp bodies are plain text with ``{{link}}`` (resolved to the per-recipient
# ``/api/v1/track/whatsapp/{uuid}`` tracker).  Every body stays under 170
# characters *including* the link so one message fits the wizard's budget.
def _whatsapp_template(
    name: str,
    text: str,
    difficulty: int,
    target_department: str = "All",
) -> dict[str, Any]:
    """Assemble a built-in WhatsApp template definition."""
    definition = _sms_template(
        name=name,
        text=text,
        difficulty=difficulty,
        variables=["link"],
        target_department=target_department,
    )
    definition["channel"] = "whatsapp"
    return definition


WHATSAPP_TEMPLATE_DEFINITIONS: list[dict[str, Any]] = [
    _whatsapp_template(
        name="WhatsApp · IT VPN Re-authentication",
        text=(
            "IT helpdesk: your VPN certificate expires tonight. "
            "Re-authenticate now to keep remote access: {{link}}"
        ),
        difficulty=3,
        target_department="IT",
    ),
    _whatsapp_template(
        name="WhatsApp · HR Bonus Confirmation",
        text=(
            "HR: your quarterly bonus is approved and awaiting your "
            "confirmation today. Review the breakdown: {{link}}"
        ),
        difficulty=4,
        target_department="HR",
    ),
    _whatsapp_template(
        name="WhatsApp · Courier Address Hold",
        text=(
            "Courier: your parcel is held at the local depot. Update the "
            "delivery address within 24h or it returns: {{link}}"
        ),
        difficulty=2,
        target_department="All",
    ),
    _whatsapp_template(
        name="WhatsApp · Executive Quick Favour",
        text=(
            "Hi, are you available? I need a discreet favour before the "
            "board meeting — open here: {{link}}"
        ),
        difficulty=5,
        target_department="Executive",
    ),
]

#: Built-in WhatsApp templates are seeded alongside the email and SMS sets.
BUILT_IN_TEMPLATES.extend(WHATSAPP_TEMPLATE_DEFINITIONS)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
async def seed_builtin_templates(db: AsyncSession, organization_id) -> int:
    """Create the eight built-in templates for an organization.

    Idempotent: templates are matched by name.  A built-in template that still
    carries the legacy wrapper is upgraded in place to the current branded
    design, so existing installations receive the new look without losing an
    administrator's customised templates.

    Args:
        db: Active session.
        organization_id: Tenant to seed.

    Returns:
        The number of templates created.
    """
    existing = {
        row.name: row
        for row in (
            await db.execute(
                select(EmailTemplate).where(
                    EmailTemplate.organization_id == organization_id,
                    EmailTemplate.is_built_in.is_(True),
                )
            )
        )
        .scalars()
        .all()
    }
    created = 0
    upgraded = 0
    for definition in BUILT_IN_TEMPLATES:
        current = existing.get(definition["name"])
        if current is not None:
            if LEGACY_WRAPPER_MARKER in (current.body_html or ""):
                current.subject = definition["subject"]
                current.body_html = definition["body_html"]
                current.difficulty_level = definition["difficulty_level"]
                current.available_variables = list(definition["available_variables"])
                upgraded += 1
            if definition.get("channel") and current.channel != definition["channel"]:
                current.channel = definition["channel"]
            if definition.get("target_department") and not current.target_department:
                current.target_department = definition["target_department"]
            if not current.design_json:
                current.design_json = legacy_design_payload(current.body_html)
            continue
        db.add(
            EmailTemplate(
                organization_id=organization_id,
                name=definition["name"],
                subject=definition["subject"],
                body_html=definition["body_html"],
                # SMS is plain text: no email design, header or footer.
                design_json=(
                    None
                    if definition.get("channel") == "sms"
                    else legacy_design_payload(definition["body_html"])
                ),
                difficulty_level=definition["difficulty_level"],
                target_department=definition.get("target_department"),
                available_variables=list(definition["available_variables"]),
                channel=definition.get("channel", "email"),
                is_built_in=True,
                is_active=True,
            )
        )
        created += 1

    # Retired built-in SMS lures stay in the database (historic campaigns still
    # reference them) but disappear from the campaign wizard: the definition
    # list above is authoritative for the active smishing catalogue.
    active_sms_names = {
        definition["name"]
        for definition in BUILT_IN_TEMPLATES
        if definition.get("channel") == "sms"
    }
    retired = 0
    for row in existing.values():
        if row.channel == "sms" and row.name not in active_sms_names and row.is_active:
            row.is_active = False
            retired += 1
    await db.flush()
    logger.info(
        "builtin_templates_seeded",
        organization_id=str(organization_id),
        created=created,
        upgraded=upgraded,
    )
    return created


async def seed_training_modules(db: AsyncSession, organization_id) -> int:
    """Create the demo training-library catalogue (idempotent).

    Args:
        db: Active session.
        organization_id: Tenant to seed.

    Returns:
        The number of modules created.
    """
    existing = await db.scalar(
        select(func.count(TrainingModule.id)).where(
            TrainingModule.organization_id == organization_id
        )
    )
    if existing:
        return 0
    for definition in DEMO_TRAINING_MODULES:
        db.add(TrainingModule(organization_id=organization_id, **definition))
    await db.flush()
    return len(DEMO_TRAINING_MODULES)


async def ensure_bootstrap_data(db: AsyncSession) -> dict[str, Any]:
    """Create the bootstrap organization, admin user and catalogue.

    Safe to call on every startup: each step is idempotent.

    Args:
        db: Active session.

    Returns:
        A summary of what was ensured.
    """
    settings = get_settings()
    organization = await db.scalar(
        select(Organization).where(Organization.domain == settings.bootstrap_org_domain)
    )
    if organization is None:
        organization = Organization(
            name=settings.bootstrap_org_name,
            domain=settings.bootstrap_org_domain,
            industry="Technology",
            allowed_test_hours={"start": 9, "end": 17},
            allow_personal_devices=False,
            adaptive_mode=True,
            max_tests_per_day=10,
            data_retention_days=settings.data_retention_days,
        )
        db.add(organization)
        await db.flush()
        logger.info("bootstrap_org_created", domain=organization.domain)

    admin = await db.scalar(
        select(User).where(User.username == settings.bootstrap_admin_username)
    )
    if admin is None:
        admin = User(
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role="admin",
            organization_id=organization.id,
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        logger.info("bootstrap_admin_created", username=admin.username)

    templates_created = 0
    if settings.seed_builtin_templates:
        templates_created = await seed_builtin_templates(db, organization.id)

    modules_created = await seed_training_modules(db, organization.id)

    demo_employees = 0
    if not settings.is_production:
        demo_employees = await seed_demo_employees(db, organization)

    await db.commit()
    return {
        "organization_id": str(organization.id),
        "templates_created": templates_created,
        "modules_created": modules_created,
        "demo_employees": demo_employees,
    }


async def seed_demo_employees(db: AsyncSession, organization: Organization) -> int:
    """Create a small set of demo employees (development only).

    Args:
        db: Active session.
        organization: Tenant to seed.

    Returns:
        The number of employees created.
    """
    existing = await db.scalar(
        select(func.count(HumanAsset.id)).where(HumanAsset.organization_id == organization.id)
    )
    if existing:
        return 0
    domain = organization.domain
    people = [
        ("Amira", "Hassan", "Finance", "Accounts Payable", 3),
        ("Daniel", "Okafor", "Engineering", "Backend Engineer", 2),
        ("Sara", "Lindqvist", "Human Resources", "HR Business Partner", 3),
        ("Marco", "Rossi", "Sales", "Account Executive", 2),
        ("Priya", "Nair", "Information Security", "Security Analyst", 5),
    ]
    for index, (first, last, dept, title, level) in enumerate(people, start=1):
        db.add(
            HumanAsset(
                organization_id=organization.id,
                email=f"{first.lower()}.{last.lower()}@{domain}",
                first_name=first,
                last_name=last,
                department=dept,
                job_title=title,
                access_level=level,
                is_active=True,
                behavioral_category="hesitant",
                behavioral_baseline={"index": index},
                device_profile={"managed": True},
                risk_profile={},
            )
        )
    await db.flush()
    return len(people)
