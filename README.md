# HUMINT Shield

**Consent-based security awareness training platform with an integrated, real-email phishing simulation engine.**

HUMINT Shield combines a complete learning-management backend (training library,
assignments, report inbox, behavioural scoring) with an additive **email campaign
module** that sends real authorized simulation emails through
[Brevo](https://www.brevo.com/), tracks opening, clicking and training completion,
and delivers immediate micro-learning to anyone who takes the bait.

Everything runs on company-owned addresses under an explicit, auditable
authorization model. Every simulated message contains a transparent disclosure
page; no credentials are ever harvested, and no user is redirected to a malicious
site — a click always lands on the training page.

---

## Table of contents

- [Feature overview](#feature-overview)
- [Architecture](#architecture)
- [Quick start (Docker Compose)](#quick-start-docker-compose)
- [Local development](#local-development)
- [Configuration](#configuration)
- [The campaign system](#the-campaign-system)
- [Tracking flow](#tracking-flow)
- [Publishing the training pages](#publishing-the-training-pages)
- [Built-in templates](#built-in-templates)
- [API reference](#api-reference)
- [Testing](#testing)
- [Security notes](#security-notes)
- [Operations](#operations)
- [Compliance basis](#compliance-basis)
- [License](#license)

---

## Feature overview

### Campaign module (new)

- **Template authoring** — rich HTML templates with `{{variable}}` interpolation,
  live preview against real employee data, per-template difficulty level.
- **Real email delivery through Brevo** — transactional send API, exponential
  backoff retries, per-recipient commit so one failure never loses a batch.
- **Deterministic tracking** — a transparent 1×1 pixel for opens, rewritten links
  for clicks, and a server-rendered training page that captures what the recipient
  typed and awards awareness points.
- **Interaction capture** — the training page presents a simulated sign-in form.
  Every field the recipient submits — identifier, password and any extra field —
  is transmitted, serialised to JSON and stored with AES-256-GCM. A secret-free
  snapshot remains available for quick tables and CSV, while the full payload is
  only readable through the authenticated dossier.
- **Second-by-second ledger** — every open, click, form render, submission,
  phishing report and completion is appended to `training_interactions` with a
  microsecond timestamp, IP address, User-Agent and optional encrypted payload.
  Repeats are preserved, not collapsed into counters.
- **Per-recipient dossier** — every campaign row opens a full report: a
  chronological timeline, delivery references, every submission with the values
  typed, the immunity score and the behavioural category. The same dossier is
  available per employee across every campaign.
- **Live monitoring board** — launching a campaign redirects straight to
  `/campaigns/{id}/live`: one card per targeted employee with the current funnel
  status, every transition timestamp to the second, the elapsed time between
  transitions, the last event with IP and device, and a live activity ticker.
  The board polls the dedicated `/live` endpoint every two seconds, so an open or
  a submission appears while the recipient is still on the page. Cards flash when
  a status changes and open the full dossier on click.
- **Campaign lifecycle** — `draft → active → completed` (plus `aborted`), with
  target selection, launch, live results and CSV export.
- **Inline or background launch** — send synchronously for small batches, or
  offload to Celery (`?background=true`) with automatic inline fallback when the
  broker is unavailable.
- **Eight built-in templates** seeded idempotently on first startup.

### Learning management (existing)

- Employee directory with AES-256-GCM encryption of sensitive fields at rest.
- Training library of micro-modules; assignments with due dates and completion.
- Phishing report inbox with triage workflow (filing a report is rewarded).
- Immunity scoring and behavioural classification.

### Platform

- JWT access/refresh authentication, bcrypt (cost 12) password hashing.
- Structured JSON logging, Prometheus metrics, request correlation IDs.
- Rate limiting, parameterized queries, typed settings, no mocks or placeholders.

---

## Architecture

```
                    ┌───────────────────────────────────────────────┐
  Mail client ─────►│ Brevo transactional API                        │
                    └───────────────────────────────────────────────┘
                                    ▲
                                    │ sib-api-v3-sdk
   ┌────────────────────────────────┴──────────────────────────────┐
   │ FastAPI (gunicorn + uvicorn workers)                          │
   │   /api/v1/...         REST API (JWT)                          │
   │   /api/v1/track/...   unauthenticated tracking endpoints      │
   │   /training/{uuid}    standalone micro-learning page          │
   │   /metrics            Prometheus                              │
   └───────┬───────────────────────────────────────┬───────────────┘
           │ SQLAlchemy 2 async                    │ Celery
   ┌───────▼────────┐                      ┌───────▼────────┐
   │ PostgreSQL 16  │                      │ Redis 7.2      │
   └────────────────┘                      └───────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │ Celery worker   │
                                          │ Celery beat     │
                                          └─────────────────┘

   ┌───────────────────────────────────────────────────────────────┐
   │ nginx (frontend container)                                    │
   │   /            React 18 SPA                                   │
   │   /api/        → backend:8000                                 │
   │   /training/   → backend:8000 (standalone page)               │
   └───────────────────────────────────────────────────────────────┘
```

### Technology stack

| Layer    | Technology                                                                 |
| -------- | -------------------------------------------------------------------------- |
| Backend  | FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, python-jose, bcrypt   |
| Jobs     | Celery + Redis (broker/result backend)                                     |
| Email    | Brevo (`sib-api-v3-sdk`)                                                   |
| Crypto   | AES-256-GCM (`cryptography`), SHA-256 key stretching for passphrases       |
| Frontend | React 18, TypeScript (strict), Vite, MUI 5, Redux Toolkit, React Query 5   |
| Forms    | React Hook Form + Zod                                                      |
| Charts   | Chart.js via react-chartjs-2                                               |
| Tests    | pytest (+ coverage), Jest + Testing Library, Playwright                    |
| Ops      | Docker Compose, nginx, Prometheus, structured logging                      |

---

## Quick start (Docker Compose)

### 1. Prerequisites

- Docker Engine 24+ with the Compose v2 plugin.
- A Brevo account with a **verified sender** address (only needed for real sends).

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
# openssl rand -hex 32   (run twice)
SECRET_KEY=<64 hex chars>
ENCRYPTION_KEY=<64 hex chars>

BREVO_API_KEY=xkeysib-...
FROM_EMAIL=security-training@your-domain.com
FROM_NAME=Security Training

# Must be reachable from recipients' mail clients (port 8080 by default).
BASE_URL=http://localhost:8080
FRONTEND_URL=http://localhost:8080
CORS_ORIGINS=http://localhost:8080
```

Leave `EMAIL_DRY_RUN=true` if you want to validate the pipeline **without**
sending real messages.

### 3. Start

```bash
docker compose up -d --build
docker compose ps
```

| Service    | URL / purpose                                        |
| ---------- | ---------------------------------------------------- |
| `frontend` | http://localhost:8080 — SPA + API reverse proxy       |
| `backend`  | http://localhost:8000 — API, docs at `/api/docs`      |
| `postgres` | internal only                                        |
| `redis`    | internal only                                        |

Sign in with the bootstrap administrator (`BOOTSTRAP_ADMIN_USERNAME` /
`BOOTSTRAP_ADMIN_PASSWORD`, default `admin` / `ChangeMe123!`) and **change the
password immediately**.

### 4. Verify

```bash
# dependency health
curl -s http://localhost:8000/healthz
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/test/health

# validate the Brevo API key without sending
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/test/brevo/verify

# send one test message
curl -s -X POST http://localhost:8000/api/v1/test/brevo \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"to_email":"you@your-domain.com"}'
```

### 5. End-to-end Brevo verification

`scripts/verify_brevo.py` performs the complete acceptance sequence against a
live deployment — authentication, configuration, dependency health, API-key
validation, a real test email, then a one-recipient campaign and the full
open → click → complete tracking chain, reconciling every counter:

```bash
python scripts/verify_brevo.py --to you@your-domain.com \
  --base-url http://localhost:8000
```

It exits non-zero unless delivery and all tracking counters reconcile.

#### If Brevo rejects the sender (401 / "unrecognised IP address")

Brevo only accepts API calls from addresses on the account allowlist. When the
server's public IP is not listed, every send fails with
`401 Unauthorized` and a body naming the address, for example:

```
We have detected you are using an unrecognised IP address 80.253.185.154.
... add the new IP address in this link:
https://app.brevo.com/security/authorised_ips
```

The platform turns that into an exact instruction instead of a dead end:

* **Settings → Email deliverability test → “Check Brevo now”** calls
  `GET /api/v1/test/brevo/verify`, shows the blocked IP and links straight to the
  Brevo page where it can be authorised;
* the API response carries `action_required: "ip_allowlist"`, `blocked_ip` and
  `action_url` so scripts can act on it;
* from the command line: `cd backend && python test_brevo.py --check`.

Fix it once by adding that address in Brevo (or by deactivating the IP
restriction), then re-run the check. On a home/dynamic connection the address
changes whenever the ISP reassigns it, so repeat the step when the message
reappears. Nothing else blocks delivery.

---

## Local development

### Backend

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example .env                              # adjust DATABASE_URL if desired
alembic upgrade head
uvicorn app.main:app --reload
```

Run the worker (optional — the launcher falls back to inline sending):

```bash
celery -A app.worker.celery_app:celery_app worker --loglevel=INFO
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev        # http://localhost:5173, /api proxied to :8000
```

### Quality gates

```bash
# backend (266 tests, >=80% coverage enforced; currently ~92%)
cd backend && python -m pytest -q
# frontend unit tests, types and lint
cd frontend && npm run typecheck && npm run lint && npm test
# browser end-to-end (needs the stack running; read-only)
cd frontend && npx playwright test e2e/smoke.spec.ts e2e/dossier.spec.ts
# live proof over the public tunnel (creates and deletes its own data)
cd backend && python test_interaction_live.py
```

`test_interaction_live.py` drives the real recipient flow over the public URL,
prints every assertion and the raw SQLite row it inspected, and deletes the
temporary employee/campaign/tracking/ledger rows afterwards.

---

## Configuration

All settings are environment variables (see `backend/app/config.py` and
`.env.example`). Highlights:

| Variable                    | Default                | Notes                                                         |
| --------------------------- | ---------------------- | ------------------------------------------------------------- |
| `DATABASE_URL`              | sqlite (dev)           | Use `postgresql+asyncpg://…` in production.                   |
| `SECRET_KEY`                | random per process     | **Must** be set in production (JWT signing).                  |
| `ENCRYPTION_KEY`            | random per process     | **Must** be set (AES-256-GCM). 64 hex chars or a passphrase.  |
| `AUTO_CREATE_SCHEMA`        | `true`                 | Set `false` in production; Alembic owns the schema.           |
| `AUTO_SEED`                 | `true`                 | Seeds org, admin, 8 templates, training catalogue.            |
| `BREVO_API_KEY`             | empty                  | When empty/placeholder, sending is disabled.                  |
| `EMAIL_DRY_RUN`             | `false`                | `true` validates and logs without dispatching.                |
| `EMAIL_MAX_RETRIES`         | `3`                    | Exponential backoff attempts per recipient.                   |
| `BASE_URL`                  | `http://localhost:8000`| Public base URL embedded in tracking links.                   |
| `SERVE_FRONTEND`            | `true`                 | Serve `frontend/dist` from the API process (one public URL).  |
| `FRONTEND_DIST`             | empty                  | Absolute path override; empty means `<repo>/frontend/dist`.    |
| `RATE_LIMIT_ENABLED`        | `true`                 | Per-scope request limiting (tracking is more permissive).     |
| `DATA_RETENTION_DAYS`       | `365`                  | Retention window surfaced to the housekeeping task.           |

> **Note on `BASE_URL`:** it is the address written into every tracking link and
> the training-page redirect. If it is not reachable from a recipient's mail
> client, opens/clicks cannot be recorded.

---

## The campaign system

### Data model

Three additive tables (existing LMS tables are untouched):

- **`email_templates`** — `id`, `organization_id`, `name`, `subject`, `body_html`,
  `difficulty_level`, `available_variables`, `is_built_in`, `is_active`, timestamps.
- **`email_campaigns`** — `id`, `organization_id`, `template_id`, `name`, `status`,
  `target_employee_ids`, `total_targets`, `sent_count`, `failed_count`,
  `opened_count`, `clicked_count`, `completed_count`, `launched_at`,
  `completed_at`, `created_by`, timestamps.
- **`email_tracking`** — one row per (campaign, employee) with a unique
  `tracking_uuid`, delivery metadata (`sent_at`, `opened_at`, `clicked_at`,
  `completed_training_at`), repeat counters (`open_count`, `click_count`),
  client context (IP, user agent) and the training-page interaction
  (`form_viewed_at`, `form_submitted_at`, `submission_count`,
  `submitted_identifier`, `submitted_fields`, `password_length`, `reported_at`,
  `submitted_password_encrypted`, `submitted_payload_encrypted`,
  `client_context`).
- **`training_interactions`** — the append-only ledger: one row per event with
  `tracking_id`, `campaign_id`, `employee_id`, `event_type`, `occurred_at`
  (microseconds), `ip_address`, `user_agent`, non-secret `details` and an
  optional `payload_encrypted` for submissions.

Indexes cover organization scoping, campaign lookups, the unique tracking UUID,
and `(campaign_id, occurred_at)` / `(employee_id, occurred_at)` for the dossiers.

Rows created before the ledger existed are **not lost**: the dossier service
reconstructs their history from the timestamps already on `email_tracking` and
marks those entries `"synthetic": true`.

### Campaign lifecycle

1. **Create** a template (or use a built-in one).
2. **Create** a campaign (`draft`) with `template_id` and `target_employee_ids`.
3. **Launch** — the launcher renders each message, rewrites links/pixel, sends via
   Brevo with retries, and commits per recipient. A recipient is only marked as
   sent after Brevo accepts the message.
4. **Track** — opens, clicks, form interaction and completions increment counters
   exactly once where appropriate (repeat opens/clicks are counted but
   de-duplicated for timestamps).
5. **Monitor live** — the UI redirects to `/campaigns/{id}/live` immediately after
   launch. Every two seconds it reads `GET …/email-campaigns/{id}/live`, which
   returns one row per recipient with the derived status (`sent`, `opened`,
   `clicked`, `form_viewed`, `submitted`, `completed`, `failed`), every transition
   timestamp, the seconds between transitions, the newest event (IP + device),
   aggregate rates and a 20-event ticker. No polling query touches encrypted
   payloads.
6. **Report** — live per-recipient report, an aggregate funnel and a CSV export.

### Delivering in the background

```bash
POST /api/v1/organizations/{org_id}/email-campaigns/{id}/launch?background=true
```

Dispatches a Celery task. If the broker is unreachable the API logs a warning and
falls back to inline sending, so a campaign launch never silently disappears.

---

## Tracking flow

```
Recipient opens email
  └─► GET  /api/v1/track/open/{uuid}        → 1×1 transparent GIF (opened_count++)
Recipient clicks a link
  └─► GET  /api/v1/track/click/{uuid}?url=… → 302 → {BASE_URL}/training/{uuid}
Recipient lands on the training page
  └─► GET  /training/{uuid}                 → simulated sign-in form
                                              (form_viewed_at)
Recipient submits the form
  └─► POST /api/v1/track/submit/{uuid}      → identifier + password + every
                                              named field, verbatim
                                              → AES-256-GCM payload stored,
                                                open/click backfilled,
                                                submission_count++,
                                                total_credential_submissions++,
                                                reclassification
Recipient (optionally) reports the message
  └─► POST /api/v1/track/report/{uuid}      → report inbox row, total_reports++,
                                              reported_at, +12 awareness points
Recipient finishes the micro-learning
  └─► POST /api/v1/track/complete/{uuid}    → completed_count++, +5 awareness points
```

Every step above also appends a row to `training_interactions`, so the exact
moment (to the microsecond), the source IP and the device are preserved even
when an action repeats.

The reveal screen is rendered server-side and only after the recipient interacts,
so the simulation is never disclosed before the form has been used.

- Tracking endpoints are **unauthenticated**; the unguessable `tracking_uuid`
  is the only credential.
- Click endpoints **never** redirect to the original (attacker) URL; they always
  redirect to the training page.
- Unknown UUIDs receive the tracking GIF / a neutral message so probes cannot
  distinguish real recipients.
- Responses carry `Cache-Control: no-store` so proxies and clients never cache a
  tracking hit.

### Where the interaction surfaces

Every event above is exposed three ways, so an operator can start from either end:

* **Per campaign** — `Campaigns → <campaign>` shows the funnel as KPI cards
  (total / sent / opened / clicked / form submitted / completed), a searchable
  recipients table with the exact time of every step, a campaign-wide live
  activity feed, and a per-row dossier (overview, chronological timeline, every
  submission verbatim, delivery references). `Export CSV` downloads the same data
  as UTF-8 CSV, including the captured values.
* **Per employee** — `Employees → <dossier icon>` opens
  `/employees/{employee_id}`: aggregate counters, every campaign with its
  timestamps, the merged ledger across campaigns, every submission and the full
  employee profile.
* **API** — `GET .../employees/{id}/dossier`,
  `GET .../email-campaigns/{id}/recipients/{employee_id}` and
  `GET .../email-campaigns/{id}/activity`.

### What is captured

| Captured                                              | Stored how                        |
| ----------------------------------------------------- | --------------------------------- |
| Whether the form was shown (every render)              | ledger + `form_viewed_at`         |
| Whether/how often it was submitted                     | ledger + `submission_count`       |
| The identifier typed                                   | plaintext `submitted_identifier`  |
| Every other named field, verbatim                      | encrypted payload                 |
| The password value, verbatim                           | **encrypted payload only**        |
| The password length                                    | `password_length`                 |
| IP address, User-Agent and browser context             | ledger + `client_context`         |
| Exact time of every event (microseconds)               | ledger `occurred_at`              |

The training page serialises every named input (`input`, `textarea`, `select`),
adds non-secret client timings (time on form, fill time, timezone, language,
viewport, referrer) and posts them. The server keeps:

* `submitted_fields` — a **secret-free snapshot** (keys containing `password`,
  `passwd`, `pwd`, `passphrase`, `secret`, `token`, `credential`, `otp`, `pin`,
  `cvv`, `cvc`, `cardnumber`, `creditcard` or `securitycode` are omitted) used
  for compact tables and quick CSV scans;
* `submitted_payload_encrypted` — the **complete verbatim mapping**, encrypted
  with AES-256-GCM (`enc:v1:` prefix), which is what the dossier shows.

> **Policy note.** Capturing the submitted password is deliberate: it is the
> evidence that defeats the “I knowingly typed fake data” defence. Treat the
> database as a high-sensitivity asset, restrict access to administrators, keep
> `ENCRYPTION_KEY` out of Git, and delete engagement data after the retention
> window. If your legal or works-council agreement forbids capturing secrets, do
> not run this build against real employees.

---

## Publishing the training pages

Recipients must be able to reach `/training/{uuid}` from anywhere, and operators
usually want to open the dashboard from the same place. The backend can serve the
built React app itself (`SERVE_FRONTEND=true`, the default), so a single tunnel
exposes **both** the dashboard and the API — no second tunnel, no CORS setup.

```powershell
cd frontend; npm run build; cd ..
powershell -ExecutionPolicy Bypass -File scripts\public-link.ps1
```

It then:

1. stops any tunnel left over from a previous run;
2. opens a new quick tunnel to `http://localhost:8000`;
3. reads the assigned `https://<random>.trycloudflare.com` address;
4. writes it into `backend\.env` as `BASE_URL` and appends it to `CORS_ORIGINS`;
5. restarts the backend so the new address takes effect;
6. polls the public URL and prints the result.

After that, `https://<random>.trycloudflare.com/` opens the dashboard and
`https://<random>.trycloudflare.com/api/docs` the API documentation. The SPA
route `/employees/{id}` also resolves on a hard refresh because the backend falls
back to `index.html` for any non-API path.

Because a quick tunnel is anonymous, its hostname is **ephemeral**: it changes on
every run and dies when the process stops. Re-run the script after a reboot (or
schedule it) to publish again. Any campaign launched after a re-run embeds the
new link automatically — previously delivered emails keep pointing at their old
(now dead) hostname.

For a **stable** hostname you need an account-based tunnel (Cloudflare named
tunnel, ngrok reserved domain, …). Those require interactive sign-up, so the
script deliberately uses the anonymous variant. To use a permanent URL, set
`BASE_URL` in `backend\.env` to it and restart the backend.

---

## Built-in templates

Seeded once per organization (idempotent, matched by name):

| # | Name                         | Subject                                                    | Level |
| - | ---------------------------- | ---------------------------------------------------------- | ----- |
| 1 | Urgent Password Change       | Urgent: Your password must be changed within 24 hours       | 3     |
| 2 | Message from Direct Manager  | Please review this document before our meeting              | 6     |
| 3 | Suspicious Login Alert       | Security Alert: Unusual login detected on your account      | 4     |
| 4 | HR Data Update Required      | Action Required: Update your employee information           | 5     |
| 5 | Overdue Invoice              | Invoice overdue — Immediate review required                 | 7     |
| 6 | Employee Bonus Announcement  | Congratulations! You've been selected for a performance bonus | 8   |
| 7 | Emergency Meeting Notice     | Emergency meeting — Your presence is required               | 5     |
| 8 | Mandatory Software Update    | Mandatory security update for your device                   | 4     |

Available placeholders: `{{first_name}}`, `{{last_name}}`, `{{email}}`,
`{{department}}`, `{{company_name}}`, `{{manager_name}}`, `{{invoice_number}}`,
`{{meeting_time}}`, `{{current_year}}`, `{{tracking_url}}`.

Every built-in body is wrapped in a table-based, 600 px branded shell (header with
the organization name, detail table, colour-coded callout, primary button and a
compliance footer) so the message renders correctly in Gmail, Outlook and Apple
Mail. On startup, built-ins still carrying the legacy plain wrapper are upgraded
in place; templates an administrator has edited are never overwritten.

The landing page (`/training/{uuid}`) is a full corporate single sign-on screen:
a branded split layout, pre-filled work email, password reveal toggle and a
low-key "Report this page" action. After submission the same page switches to the
educational reveal, listing the red flags and the exact values that were recorded.

---

## API reference

Interactive documentation: `http://<host>/api/docs` (OpenAPI at `/api/openapi.json`).

### Authentication

| Method | Path                     | Description                        |
| ------ | ------------------------ | ---------------------------------- |
| POST   | `/api/v1/auth/login`     | Obtain access + refresh tokens     |
| POST   | `/api/v1/auth/refresh`   | Refresh an access token            |
| POST   | `/api/v1/auth/logout`    | Client-side session teardown       |
| GET    | `/api/v1/auth/me`        | Current user                       |

### Campaign module

| Method | Path                                                              |
| ------ | ----------------------------------------------------------------- |
| GET    | `/api/v1/organizations/{org_id}/email-templates`                   |
| POST   | `/api/v1/organizations/{org_id}/email-templates`                   |
| PUT    | `/api/v1/organizations/{org_id}/email-templates/{id}`              |
| DELETE | `/api/v1/organizations/{org_id}/email-templates/{id}`              |
| POST   | `/api/v1/organizations/{org_id}/email-templates/{id}/preview`      |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns`                   |
| POST   | `/api/v1/organizations/{org_id}/email-campaigns`                   |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}`              |
| DELETE | `/api/v1/organizations/{org_id}/email-campaigns/{id}`              |
| POST   | `/api/v1/organizations/{org_id}/email-campaigns/{id}/launch`       |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}/results`      |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}/live`         | Live monitoring board (poll every 2s) |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}/export`       |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}/recipients/{employee_id}` | One recipient's full dossier |
| GET    | `/api/v1/organizations/{org_id}/email-campaigns/{id}/activity`     | Campaign-wide interaction ledger |
| GET    | `/api/v1/organizations/{org_id}/employees/{id}/dossier`            | Employee dossier across campaigns |

### Tracking (unauthenticated)

| Method | Path                                     | Description                              |
| ------ | ---------------------------------------- | ---------------------------------------- |
| GET    | `/api/v1/track/open/{tracking_uuid}`     | Transparent GIF, records an open         |
| GET    | `/api/v1/track/click/{tracking_uuid}`    | Records a click, 302 to the training page|
| POST   | `/api/v1/track/submit/{tracking_uuid}`   | Records the simulated form submission    |
| POST   | `/api/v1/track/report/{tracking_uuid}`   | Records that the recipient spotted it    |
| POST   | `/api/v1/track/complete/{tracking_uuid}` | Records micro-learning completion        |
| GET    | `/training/{tracking_uuid}`              | Sign-in form, then the educational reveal|

### LMS and diagnostics

`/api/v1/organizations/{org_id}/dashboard`, `/employees` (+`/bulk`,
`/{id}/timeline`), `/training-modules`, `/assignments` (+`/{id}/complete`),
`/reports` (+`/{id}`), and `/api/v1/test/{health,config,brevo,brevo/verify}`.

---

## Testing

### Backend

```bash
cd backend
python -m pytest -q                       # full suite
python -m pytest --cov=app --cov-report=term-missing
```

- Runs against SQLite (`aiosqlite`) for hermetic, dependency-free execution; the
  dialect-aware Alembic migration is verified on both SQLite and PostgreSQL.
- `pyproject.toml` enforces `--cov-fail-under=80`.

### Frontend

```bash
cd frontend
npm run typecheck      # tsc --noEmit, strict mode
npm run lint           # eslint, zero warnings allowed
npm test               # jest + testing-library
npm run build          # tsc -b && vite build
```

### End-to-end

```bash
cd frontend
E2E_BASE_URL=http://localhost:8080 E2E_ADMIN_USER=admin E2E_ADMIN_PASSWORD=... \
  npx playwright test
```

`npx playwright test e2e/screenshots.spec.ts` additionally writes full-page PNGs
to `docs/screenshots/` (browser documentation and release evidence). Pass
`E2E_BACKEND_URL` and `E2E_TRACKING_UUID` to also capture the recipient
micro-learning page. `docs/screenshots/preview.html` is a self-contained gallery
of that output.

> **Two implementations of the micro-learning page.** The recipient link in every
> campaign email points at `GET /training/{tracking_uuid}` served by the backend
> as plain HTML, because mail clients do not run JavaScript. The React route
> `frontend/src/pages/TrainingPage.tsx` implements the same flow for deployments
> that serve the SPA statically without the `/training/` reverse-proxy rule. Both
> are covered by tests.

---

## Security notes

- **Authorization first.** Only send to addresses covered by your acceptable-use
  policy and an approved awareness program. Record that authorization.
- **Credential capture is deliberate and encrypted.** The training page
  transmits every value typed, including the password, so the record is complete
  and cannot be disputed. Plaintext secrets are never written to the database
  (only `enc:v1:` AES-256-GCM tokens), never logged, and never returned by
  unauthenticated endpoints. The secret-free `submitted_fields` snapshot is used
  for tables; the dossier reveals the encrypted payload only after authentication.
  Treat the database and `ENCRYPTION_KEY` as high-sensitivity assets, restrict
  dashboard access, and honour your retention policy. If capturing secrets is not
  permitted in your jurisdiction, do not run this build against employees.
- **Secrets.** `SECRET_KEY` and `ENCRYPTION_KEY` must be strong and unique per
  environment. Rotate them via your secret manager, not in Git.
- **Encryption at rest.** Sensitive employee fields use AES-256-GCM
  (`enc:v1:<base64(nonce‖ciphertext‖tag)>`); submitted form payloads use the same
  scheme.
- **Least privilege.** Roles are `admin`, `manager`, `viewer`; destructive and
  configuration endpoints require `admin`/`manager`. Dossiers are scoped to the
  caller's organization.
- **Rate limiting.** Per-scope limits protect auth and API endpoints; tracking is
  throttled more permissively to tolerate mail-client prefetching.
- **Supply chain.** Dependencies are pinned; run `pip-audit` / `npm audit` in CI.
- **Data retention.** `DATA_RETENTION_DAYS` bounds how long engagement data is
  kept; align it with your privacy notice and applicable law.

---

## Operations

### Backups (PostgreSQL)

Use [pgBackRest](https://pgbackrest.org/) for physical backups, WAL archiving and
point-in-time recovery of the `pgdata` volume:

```ini
# /etc/pgbackrest/pgbackrest.conf
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=4
start-fast=y

[humint]
pg1-path=/var/lib/postgresql/data/pgdata
```

```bash
pgbackrest --stanza=humint stanza-create
pgbackrest --stanza=humint --type=full backup
pgbackrest --stanza=humint --type=incr backup
pgbackrest --stanza=humint --delta --type=time \
  --target="2026-01-31 12:00:00+00" restore
```

Schedule full backups weekly and incremental backups daily; store `repo1-path`
off-host. Test restores quarterly.

### Migrations

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
```

`AUTO_CREATE_SCHEMA=false` is recommended in production so Alembic is the single
source of truth for schema changes.

Applied revisions:

| Revision | Purpose                                                        |
| -------- | -------------------------------------------------------------- |
| `0001_initial_lms` | Organizations, users, employees, LMS tables           |
| `0002_email_campaigns` | `email_templates`, `email_campaigns`, `email_tracking` |
| `0003_training_interactions` | training-page interaction columns on `email_tracking` |
| `0004_interaction_ledger` | encrypted submission payloads + `training_interactions` ledger |

### Observability

- Structured JSON logs with `request_id` correlation on every request.
- Prometheus metrics at `/metrics`; scrape from your monitoring stack.
- Health: `/healthz` (liveness) and `/api/v1/test/health` (dependency probe).

---

## Compliance basis

HUMINT Shield supports (and documents evidence for) the awareness-training
requirements of:

- **ISO/IEC 27001:2022 A.7.2.2** — information security awareness, education and
  training.
- **NIST SP 800-50** & **NIST SP 800-53 AT-2** — literacy training and awareness.
- **PCI-DSS v4.0 requirement 12.6** — security awareness program.
- **HIPAA Security Rule §164.308(a)(5)** — workforce security awareness training.
- **GDPR Article 32** — security of processing, including staff awareness.

Retain campaign results and CSV exports as training records for your auditors.

---

## License

Released under the [MIT License](LICENSE).

> **Ethical use.** HUMINT Shield is intended solely for authorized security
> awareness training against your own organization's addresses. Deploying it to
> deceive or harm people who have not consented is prohibited and may be illegal.
