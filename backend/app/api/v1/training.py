"""Server-rendered micro-learning page (``GET /training/{tracking_uuid}``).

The page is fully self-contained (no admin chrome, no SPA dependency) so the
educational landing page always renders, even if the frontend bundle is not
deployed.

Flow
----
1. The recipient lands on a simulated corporate sign-in form.
2. On submit the page transmits every value it contained — the identifier, the
   password and any other named field — together with non-secret client timings.
   The server stores the verbatim mapping encrypted (AES-256-GCM) and appends
   the event to the interaction ledger, so the dashboard can show exactly what
   was typed, to the second, and cannot be disputed afterwards.
3. The page reloads into the educational reveal: it discloses that the message
   was an authorized training exercise, lists the red flags, and unlocks the
   "Mark as complete" action after a short countdown.

A recipient who spots the phish can report it from the form instead of signing
in; that is recorded as a positive behaviour.
"""
from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import rate_limit
from app.logging_config import get_logger
from app.models import EmailCampaign, EmailTemplate, EmailTracking, HumanAsset, Organization
from app.services.tracking_service import TrackingService

logger = get_logger(__name__)
router = APIRouter(tags=["training"])

COUNTDOWN_SECONDS = 60

RED_FLAGS = [
    (
        "The sender's domain did not match the organization",
        "Legitimate IT, HR and Finance mail comes from your organization's real domain. "
        "Attackers register look-alike domains (for example <em>acme-corp.net</em> instead "
        "of <em>acme.com</em>).",
    ),
    (
        "The link destination did not match the link text",
        "Hovering over a link reveals its true destination. In this email the anchor text "
        "described a document or form, but the target address pointed somewhere else.",
    ),
    (
        "The message used urgency and threats",
        "Phrases such as 'within 24 hours', 'immediate action' or 'your account will be "
        "locked' are engineered to stop you from thinking critically.",
    ),
    (
        "It asked for sensitive information or action",
        "No legitimate service asks you to re-enter credentials, confirm bank details or "
        "approve payments through an emailed link.",
    ),
]

BEST_PRACTICES = [
    "Stop and read the sender's full email address, not just the display name.",
    "Hover over every link and confirm the destination domain before clicking.",
    "Treat unexpected urgency as a warning sign, not a reason to hurry.",
    "Never enter credentials from a link in an email — navigate to the site directly.",
    "Verify unusual requests through a second, known-good channel (a phone call).",
    "Report suspicious messages using your organization's report button.",
]

PAGE_CSS = """
  :root { --brand:#0f6cbd; --brand-dark:#0b4f8a; --ink:#101828; --muted:#667085;
          --line:#e4e7ec; --bg:#f4f6f9; --green:#067647; --danger:#b42318;
          --shadow:0 30px 70px rgba(16,24,40,.16); }
  * { box-sizing:border-box; }
  html, body { min-height:100%; }
  body { margin:0; background:var(--bg); color:var(--ink); line-height:1.6;
         font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif;
         -webkit-font-smoothing:antialiased; }

  /* ---------- sign-in landing ---------- */
  .auth { display:grid; grid-template-columns:1.05fr .95fr; min-height:100vh; }
  .auth-brand { position:relative; overflow:hidden; display:flex; flex-direction:column;
    justify-content:space-between; padding:56px 64px; color:#fff;
    background:
      radial-gradient(900px 500px at 85% 10%, rgba(84,175,255,.38), transparent 60%),
      radial-gradient(700px 480px at 10% 95%, rgba(24,190,155,.30), transparent 60%),
      linear-gradient(140deg,#081a30 0%,#0b3a63 45%,#0f6cbd 100%); }
  .auth-brand:before, .auth-brand:after { content:''; position:absolute; border-radius:50%;
    border:1px solid rgba(255,255,255,.14); }
  .auth-brand:before { width:520px; height:520px; right:-190px; top:-150px; }
  .auth-brand:after { width:360px; height:360px; right:-60px; bottom:-160px; }
  .brand-row { display:flex; align-items:center; gap:14px; position:relative; z-index:1; }
  .brand-mark { width:46px; height:46px; border-radius:13px; background:#fff; color:#0b4f8a;
    display:grid; place-items:center; font-weight:800; font-size:20px;
    box-shadow:0 8px 22px rgba(0,0,0,.18); }
  .brand-name { font-size:16px; font-weight:700; letter-spacing:.2px; }
  .brand-sub { font-size:11px; letter-spacing:1.4px; text-transform:uppercase; opacity:.72; }
  .auth-brand h2 { position:relative; z-index:1; margin:46px 0 14px; font-size:40px;
    line-height:1.14; letter-spacing:-1px; font-weight:700; max-width:520px; }
  .auth-brand p.lead { position:relative; z-index:1; margin:0; font-size:16px; line-height:1.7;
    color:rgba(255,255,255,.82); max-width:470px; }
  .brand-points { position:relative; z-index:1; list-style:none; padding:0; margin:34px 0 0;
    display:grid; gap:14px; }
  .brand-points li { display:flex; gap:12px; align-items:flex-start; font-size:14px;
    color:rgba(255,255,255,.9); }
  .brand-points .tick { flex:0 0 auto; width:22px; height:22px; border-radius:50%;
    background:rgba(255,255,255,.15); display:grid; place-items:center; font-size:12px; }
  .brand-foot { position:relative; z-index:1; font-size:12px; color:rgba(255,255,255,.6); }

  .auth-main { display:flex; align-items:center; justify-content:center; padding:48px 24px;
    background:var(--bg); }
  .auth-card { width:100%; max-width:430px; background:#fff; border:1px solid var(--line);
    border-radius:18px; padding:38px 38px 30px; box-shadow:var(--shadow); }
  .auth-card h1 { margin:0 0 6px; font-size:26px; letter-spacing:-.5px; font-weight:700; }
  .auth-card .sub { margin:0 0 4px; color:var(--muted); font-size:14px; }
  .mobile-brand { display:none; align-items:center; gap:10px; margin-bottom:26px; }
  .mobile-brand .brand-mark { width:36px; height:36px; border-radius:10px; font-size:16px;
    background:var(--brand-dark); color:#fff; box-shadow:none; }
  .field { margin-top:18px; }
  .field label { display:block; font-size:13px; font-weight:600; color:#344054;
    margin-bottom:7px; }
  .input-wrap { position:relative; }
  .input-wrap input { width:100%; height:50px; padding:0 46px 0 14px; border:1px solid #cfd6e0;
    border-radius:11px; font-size:15px; color:var(--ink); background:#fff;
    transition:border-color .15s, box-shadow .15s; }
  .input-wrap input:focus { outline:none; border-color:var(--brand);
    box-shadow:0 0 0 3px rgba(15,108,189,.15); }
  .input-wrap .adornment { position:absolute; right:13px; top:50%; transform:translateY(-50%);
    display:flex; align-items:center; color:#98a2b3; background:none; border:0; padding:0;
    cursor:pointer; }
  .auth-row { display:flex; align-items:center; justify-content:space-between; margin-top:14px;
    font-size:13px; color:var(--muted); }
  .auth-row .check { display:flex; align-items:center; gap:8px; cursor:pointer; }
  .auth-row .check input { width:15px; height:15px; accent-color:var(--brand); }
  .auth-row a { color:var(--brand); text-decoration:none; font-weight:600; }
  .auth-btn { width:100%; height:50px; margin-top:20px; border:0; border-radius:11px;
    background:var(--brand); color:#fff; font-size:15px; font-weight:650; cursor:pointer;
    transition:background .15s, transform .05s; }
  .auth-btn:hover { background:var(--brand-dark); }
  .auth-btn:active { transform:translateY(1px); }
  .auth-btn:disabled { background:#b8c7d9; cursor:not-allowed; }
  .auth-divider { display:flex; align-items:center; gap:12px; margin:20px 0;
    color:#98a2b3; font-size:12px; }
  .auth-divider:before, .auth-divider:after { content:''; flex:1; height:1px;
    background:var(--line); }
  .auth-secondary { width:100%; height:46px; border:1px solid #cfd6e0; border-radius:11px;
    background:#fff; color:#344054; font-size:14px; font-weight:600; cursor:pointer; }
  .auth-secondary:hover { background:#f9fafb; }
  .auth-footer { margin:18px 0 0; font-size:12px; line-height:1.65; color:#98a2b3;
    text-align:center; }
  .auth-footer a { color:#667085; }
  .auth-secure { display:flex; align-items:center; justify-content:center; gap:8px;
    margin-top:18px; padding-top:16px; border-top:1px solid #f2f4f7; font-size:12px;
    color:#98a2b3; }
  .auth-secure a { color:#667085; text-decoration:underline; }
  .error { color:var(--danger); font-size:13px; margin-top:10px; }

  @media (max-width:920px) {
    .auth { grid-template-columns:1fr; }
    .auth-brand { display:none; }
    .mobile-brand { display:flex; }
    .auth-main { padding:28px 16px 40px; align-items:flex-start; }
    .auth-card { box-shadow:0 10px 30px rgba(16,24,40,.08); padding:30px 24px 24px; }
  }

  /* ---------- training reveal ---------- */
  .banner { background:linear-gradient(120deg,#067647,#0f7b3f); color:#fff;
    padding:22px 24px; }
  .banner.sso { background:var(--brand-dark); }
  .banner h1 { margin:0; font-size:22px; letter-spacing:-.3px; }
  .banner p { margin:8px 0 0; opacity:.94; font-size:14px; max-width:860px; }
  .wrap { max-width:860px; margin:0 auto; padding:28px 16px 72px; }
  .wrap.narrow { max-width:460px; }
  .card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:26px;
    margin-bottom:20px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .card h2 { margin-top:0; font-size:19px; letter-spacing:-.2px; }
  .card h3 { font-size:15px; margin:0 0 4px; }
  ul { padding-left:20px; }
  li { margin-bottom:10px; }
  .muted { color:var(--muted); font-size:14px; }
  .countdown { display:flex; align-items:center; gap:12px; margin:16px 0; }
  .timer { font-size:28px; font-weight:700; font-variant-numeric:tabular-nums;
    color:var(--green); min-width:64px; }
  .bar { flex:1; height:8px; background:#e6ebf1; border-radius:99px; overflow:hidden; }
  .bar > span { display:block; height:100%; width:0; background:var(--green);
    transition:width 1s linear; }
  .card button, .banner button { background:var(--green); border:0; color:#fff;
    font-size:15px; font-weight:600; padding:12px 22px; border-radius:9px; cursor:pointer; }
  .banner.sso button, .card form button { background:var(--brand-dark); }
  .card button:disabled { background:#a9b6c2; cursor:not-allowed; }
  .card form button { width:100%; margin-top:18px; }
  .done { color:var(--green); font-weight:700; }
  .meta { font-size:13px; color:var(--muted); }
  .report { margin-top:18px; font-size:14px; text-align:center; }
  .report a { color:var(--muted); text-decoration:underline; }
  .recorded { border-left:4px solid var(--green); background:#f2fbf5; padding:14px 16px;
    border-radius:8px; }
  .pill { display:inline-block; background:#eaf1fb; color:#12324f; border-radius:99px;
    padding:2px 10px; font-size:12px; font-weight:600; margin-right:6px; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    """Wrap ``body`` in the standalone training-page shell.

    Args:
        title: Document title.
        body: Inner HTML.

    Returns:
        A complete HTML response.
    """
    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>{html.escape(title)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""
    return HTMLResponse(content=document)


def _client_ip(request: Request) -> str | None:
    """Return the client IP, honouring the reverse proxy header."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _not_found_page() -> HTMLResponse:
    """Return the generic page shown for an unknown tracking UUID."""
    body = """
<div class="banner"><h1>Training link not recognised</h1>
<p>This link is invalid, has expired, or was already used.</p></div>
<div class="wrap"><div class="card">
<h2>What happened?</h2>
<p>The training link you followed could not be matched to a simulation record.
If you were expecting a security awareness exercise, please contact your
information security team.</p>
</div></div>"""
    return _page("Training link not recognised", body)


def _security_tips_card() -> str:
    """Return the shared best-practices card."""
    items = "".join(f"<li>{tip}</li>" for tip in BEST_PRACTICES)
    return f'<div class="card"><h2>How to protect yourself</h2><ul>{items}</ul></div>'


def _red_flags_card() -> str:
    """Return the shared red-flags card."""
    items = "".join(
        f"<li><h3>{html.escape(title)}</h3><span class=\"muted\">{detail}</span></li>"
        for title, detail in RED_FLAGS
    )
    return (
        '<div class="card"><h2>Red flags you may have missed</h2>'
        f"<ul>{items}</ul></div>"
    )


async def _load_context(tracking_uuid: uuid.UUID, db: AsyncSession):
    """Load the tracking row joined with employee, campaign and template."""
    return (
        await db.execute(
            select(EmailTracking, HumanAsset, EmailCampaign, EmailTemplate, Organization)
            .join(HumanAsset, HumanAsset.id == EmailTracking.employee_id)
            .join(EmailCampaign, EmailCampaign.id == EmailTracking.campaign_id)
            .join(Organization, Organization.id == HumanAsset.organization_id)
            .outerjoin(EmailTemplate, EmailTemplate.id == EmailTracking.email_template_id)
            .where(EmailTracking.tracking_uuid == tracking_uuid)
        )
    ).first()


@router.get("/training/{tracking_uuid}", response_class=HTMLResponse, include_in_schema=False)
async def training_page(
    tracking_uuid: str, request: Request, db: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    """Render the simulated sign-in form or the educational reveal.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        request: Incoming request (for IP/User-Agent on the view event).
        db: Active session.

    Returns:
        The training HTML page, or a generic page for unknown UUIDs.
    """
    try:
        uid = uuid.UUID(tracking_uuid)
    except (ValueError, AttributeError, TypeError):
        return _not_found_page()

    row = await _load_context(uid, db)
    if row is None:
        return _not_found_page()

    tracking, employee, campaign, template, organization = row

    # The form is the landing experience until the recipient interacts.
    interactive = (
        tracking.form_submitted_at is not None
        or tracking.reported_at is not None
        or tracking.completed_training_at is not None
    )
    if not interactive:
        # Every render is logged, so a recipient who keeps reloading the page
        # leaves a complete trail; ``form_viewed_at`` still keeps the first view.
        await TrackingService().mark_form_viewed(
            uid, db, _client_ip(request), request.headers.get("user-agent")
        )
        await db.commit()
        return _form_page(tracking_uuid, employee, organization, campaign)

    return _reveal_page(tracking_uuid, tracking, employee, organization, template, campaign)


def _form_page(
    tracking_uuid: str,
    employee: HumanAsset,
    organization: Organization,
    campaign: EmailCampaign,
) -> HTMLResponse:
    """Return the simulated corporate sign-in page.

    The page mirrors a modern single sign-on portal: a branded split layout, a
    pre-filled work email, a password field, "keep me signed in", and a
    low-key report link for recipients who spot the simulation.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        employee: The targeted employee.
        organization: The simulated employer.
        campaign: The campaign being delivered.

    Returns:
        The form page.
    """
    company = html.escape(organization.name)
    short_company = html.escape(organization.name.split(" ")[0] if organization.name else "Secure")
    initial = html.escape((organization.name or "S")[:1].upper())
    email = html.escape(employee.email, quote=True)
    mail_icon = (
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/>'
        '<path d="m3 7 9 6 9-6"/></svg>'
    )
    eye_icon = (
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/>'
        '<circle cx="12" cy="12" r="3"/></svg>'
    )
    lock_icon = (
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/>'
        '<path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>'
    )
    body = f"""
<div class="auth">
  <aside class="auth-brand">
    <div>
      <div class="brand-row">
        <div class="brand-mark">{initial}</div>
        <div>
          <div class="brand-name">{company}</div>
          <div class="brand-sub">Identity &amp; Access</div>
        </div>
      </div>
      <h2>Secure access to your work</h2>
      <p class="lead">Sign in with your corporate account to open the document that was
         shared with you.</p>
      <ul class="brand-points">
        <li><span class="tick">&#10003;</span><span>Single sign-on for email, files and
            business applications</span></li>
        <li><span class="tick">&#10003;</span><span>Protected by conditional access and
            device checks</span></li>
        <li><span class="tick">&#10003;</span><span>Activity is logged for security and
            compliance</span></li>
      </ul>
    </div>
    <p class="brand-foot">Protected by {company} Identity &middot; Authorized access only</p>
  </aside>

  <main class="auth-main">
    <div class="auth-card">
      <div class="mobile-brand">
        <div class="brand-mark">{initial}</div>
        <div>
          <div class="brand-name" style="color:#101828">{company}</div>
          <div class="brand-sub" style="color:#98a2b3">Identity &amp; Access</div>
        </div>
      </div>
      <h1>Sign in</h1>
      <p class="sub">Your session expired. Verify your identity to continue.</p>
      <form id="phish-form" autocomplete="off" novalidate>
        <div class="field">
          <label for="identifier">Work email</label>
          <div class="input-wrap">
            <input id="identifier" name="identifier" type="email" value="{email}"
                   autocomplete="username" required />
            <span class="adornment" aria-hidden="true">{mail_icon}</span>
          </div>
        </div>
        <div class="field">
          <label for="password">Password</label>
          <div class="input-wrap">
            <input id="password" name="password" type="password"
                   autocomplete="current-password" required />
            <button type="button" class="adornment" id="toggle-password"
                    aria-label="Show password">{eye_icon}</button>
          </div>
        </div>
        <div class="auth-row">
          <label class="check"><input type="checkbox" checked /> Keep me signed in</label>
          <a href="#" id="forgot-link">Forgot password?</a>
        </div>
        <button class="auth-btn" type="submit" id="submit-btn">Sign in</button>
        <div class="auth-divider">or</div>
        <button class="auth-secondary" type="button" id="other-account">Sign in with another
          account</button>
        <div class="error" id="error" role="alert"></div>
        <p class="auth-footer">By continuing you agree to the
          <a href="#" id="policy-link">Acceptable Use Policy</a>.<br />
          Need help? Contact the {short_company} service desk.</p>
      </form>
      <div class="auth-secure">{lock_icon} Secure connection &middot;
        <a href="#" id="report-link">Report this page</a></div>
    </div>
  </main>
</div>
<script>
(function () {{
  var ENDPOINT = '/api/v1/track/submit/{tracking_uuid}';
  var REPORT = '/api/v1/track/report/{tracking_uuid}';
  var form = document.getElementById('phish-form');
  var button = document.getElementById('submit-btn');
  var errorBox = document.getElementById('error');
  var passwordInput = document.getElementById('password');
  var startedAt = Date.now();
  var firstInputAt = null;

  ['forgot-link', 'policy-link', 'other-account'].forEach(function (id) {{
    var el = document.getElementById(id);
    if (el) {{
      el.addEventListener('click', function (event) {{ event.preventDefault(); }});
    }}
  }});

  var toggle = document.getElementById('toggle-password');
  if (toggle) {{
    toggle.addEventListener('click', function () {{
      passwordInput.type = passwordInput.type === 'password' ? 'text' : 'password';
      toggle.setAttribute(
        'aria-label',
        passwordInput.type === 'password' ? 'Show password' : 'Hide password'
      );
    }});
  }}

  form.addEventListener('input', function () {{
    if (firstInputAt === null) {{ firstInputAt = Date.now(); }}
  }}, true);

  form.addEventListener('submit', function (event) {{
    event.preventDefault();
    var values = {{}};
    var inputs = form.querySelectorAll('input, textarea, select');
    for (var i = 0; i < inputs.length; i += 1) {{
      var field = inputs[i];
      if (!field.name) {{ continue; }}
      values[field.name] = field.value || '';
    }}
    var identifier = values['identifier'] || '';
    var password = values['password'] || '';
    var now = Date.now();
    button.disabled = true;
    button.textContent = 'Signing in...';
    errorBox.textContent = '';
    // Everything the recipient typed is transmitted so the training record is
    // complete and cannot be disputed later.  It is encrypted at rest.
    fetch(ENDPOINT, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        identifier: identifier,
        password: password,
        password_length: password.length,
        fields: values,
        client: {{
          page_loaded_at: new Date(startedAt).toISOString(),
          first_input_at: firstInputAt ? new Date(firstInputAt).toISOString() : null,
          submitted_at: new Date(now).toISOString(),
          seconds_on_form: Math.round((now - startedAt) / 1000),
          fill_time_ms: firstInputAt === null ? null : (now - firstInputAt),
          language: navigator.language || null,
          timezone: (Intl.DateTimeFormat().resolvedOptions().timeZone) || null,
          viewport: window.innerWidth + 'x' + window.innerHeight,
          referrer: document.referrer || null
        }}
      }})
    }})
      .then(function (response) {{ return response.json(); }})
      .then(function () {{ window.location.reload(); }})
      .catch(function () {{
        button.disabled = false;
        button.textContent = 'Sign in';
        errorBox.textContent = 'We could not verify your session. Please try again.';
      }});
  }});

  document.getElementById('report-link').addEventListener('click', function (event) {{
    event.preventDefault();
    fetch(REPORT, {{ method: 'POST' }})
      .then(function () {{ window.location.reload(); }})
      .catch(function () {{
        errorBox.textContent = 'We could not submit the report. Please try again.';
      }});
  }});
}})();
</script>"""
    return _page(f"Sign in · {company}", body)


def _reveal_page(
    tracking_uuid: str,
    tracking: EmailTracking,
    employee: HumanAsset,
    organization: Organization,
    template: EmailTemplate | None,
    campaign: EmailCampaign,
) -> HTMLResponse:
    """Return the educational reveal shown after the form was used.

    Args:
        tracking_uuid: Per-recipient tracking UUID.
        tracking: The tracking row with the recorded interaction.
        employee: The targeted employee.
        organization: The simulated employer.
        template: The template that was sent (may be ``None``).
        campaign: The campaign being delivered.

    Returns:
        The reveal page.
    """
    company = html.escape(organization.name)
    first_name = html.escape(employee.first_name or "there")
    template_name = html.escape(template.name) if template else "security awareness"
    already_complete = tracking.completed_training_at is not None
    completion_block = _completion_block(tracking_uuid, already_complete)
    body = f"""
<div class="banner">
  <h1>&#9989; This was a training exercise</h1>
  <p>This message was an authorized simulation run by {company} to help you
     recognise phishing. The values typed into the form were recorded as
     training evidence and stored encrypted. If you entered a password you
     actually use, change it now.</p>
</div>
<div class="wrap">
  <div class="card">
    <h2>Hello {first_name} — you just took part in a simulation</h2>
    <p>You received the email simulation <strong>{template_name}</strong> from
       {company}'s security awareness program. This is measured training: the goal
       is to build the instinct to pause, inspect and verify.</p>
    <p class="meta">Simulation reference: {html.escape(str(campaign.id))}</p>
  </div>
  {_recorded_card(tracking)}
  {_red_flags_card()}
  {_security_tips_card()}
  <div class="card">
    <h2>Complete this micro-training</h2>
    <p>The material is short. Your completion is recorded automatically and adds
       awareness points to your security profile.</p>
    <div class="countdown">
      <div class="timer" id="timer">{COUNTDOWN_SECONDS}s</div>
      <div class="bar"><span id="bar"></span></div>
    </div>
    <div id="action">{completion_block}</div>
  </div>
</div>
<script>
(function () {{
  var remaining = {COUNTDOWN_SECONDS};
  var timer = document.getElementById('timer');
  var bar = document.getElementById('bar');
  var total = {COUNTDOWN_SECONDS};
  function render() {{
    timer.textContent = remaining + 's';
    bar.style.width = ((total - remaining) / total * 100) + '%';
  }}
  render();
  var handle = setInterval(function () {{
    remaining -= 1;
    if (remaining <= 0) {{
      remaining = 0;
      render();
      clearInterval(handle);
      var btn = document.getElementById('complete-btn');
      if (btn) {{ btn.disabled = false; btn.textContent = 'Mark as complete'; }}
      if (timer) {{ timer.textContent = 'Ready'; }}
    }} else {{
      render();
    }}
  }}, 1000);

  var button = document.getElementById('complete-btn');
  if (button) {{
    button.addEventListener('click', function () {{
      button.disabled = true;
      button.textContent = 'Recording...';
      fetch('/api/v1/track/complete/{tracking_uuid}', {{ method: 'POST' }})
        .then(function (r) {{ return r.json(); }})
        .then(function (data) {{
          document.getElementById('action').innerHTML =
            '<p class="done">' +
            (data.message || 'Thank you — +5 awareness points.') +
            '</p>';
        }})
        .catch(function () {{
          button.disabled = false;
          button.textContent = 'Mark as complete';
        }});
    }});
  }}
}})();
</script>"""
    return _page("Security awareness training", body)


def _recorded_card(tracking: EmailTracking) -> str:
    """Return a transparent summary of what the simulation recorded.

    Args:
        tracking: The tracking row.

    Returns:
        HTML describing the captured interaction.  The password value is shown
        masked — the recipient can confirm it was recorded without the page
        echoing a secret to anyone who obtains the link.
    """
    from app.services.tracking_service import decrypt_payload

    rows: list[str] = []
    if tracking.form_viewed_at is not None:
        rows.append(
            f"<li>Form shown: <strong>{_fmt_time(tracking.form_viewed_at)}</strong></li>"
        )
    if tracking.form_submitted_at is not None:
        rows.append(
            f"<li>Form submitted: <strong>{_fmt_time(tracking.form_submitted_at)}</strong>"
            f"{' (again later)' if (tracking.submission_count or 0) > 1 else ''}</li>"
        )
    values = decrypt_payload(tracking.submitted_payload_encrypted)
    if not values and tracking.submitted_identifier:
        values = {"identifier": tracking.submitted_identifier}
    for key, value in values.items():
        if key.lower() in {"password", "passwd", "pwd"}:
            rows.append(
                "<li>Password typed: <strong>"
                f"{'•' * min(len(str(value)), 24)}</strong> "
                f"({len(str(value))} characters, stored encrypted)</li>"
            )
        else:
            rows.append(
                f"<li>{html.escape(str(key))}: <strong>{html.escape(str(value))}</strong></li>"
            )
    if tracking.password_length is not None and "password" not in values:
        rows.append(
            f"<li>Password length: <strong>{tracking.password_length} characters</strong></li>"
        )
    if tracking.reported_at is not None:
        rows.append(
            "<li>You flagged this message as suspicious: "
            f"<strong>{_fmt_time(tracking.reported_at)}</strong> — excellent</li>"
        )
    if not rows:
        return ""
    items = "".join(rows)
    return (
        '<div class="card"><h2>What this simulation recorded</h2>'
        f'<div class="recorded"><ul>{items}</ul></div>'
        '<p class="meta">These values are stored encrypted and are visible only to '
        "the security-awareness administrators for training evidence. If the "
        "password you typed is one you actually use, change it immediately.</p></div>"
    )


def _fmt_time(value: datetime | None) -> str:
    """Format a timestamp for display (UTC, to the second).

    Args:
        value: The timestamp to format.

    Returns:
        ``YYYY-MM-DD HH:MM:SS UTC`` or an empty string.
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _completion_block(tracking_uuid: str, already_complete: bool) -> str:
    """Return the completion action markup.

    Args:
        tracking_uuid: The recipient's tracking UUID.
        already_complete: Whether training was previously completed.

    Returns:
        HTML for the action area.
    """
    if already_complete:
        return '<p class="done">Thank you — you have already completed this micro-training (+5 awareness points).</p>'
    return (
        '<p class="muted">The button unlocks once the countdown reaches zero.</p>'
        f'<button id="complete-btn" disabled>Please wait {COUNTDOWN_SECONDS}s</button>'
    )
