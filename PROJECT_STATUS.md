# HUMINT Shield — Project Status

- **Last updated:** 2026-10-25
- **Branch:** `main`
- **Runtime:** Windows, Python 3.14.5, Node/Jest, SQLite
- **Local backend:** `http://127.0.0.1:8000`
- **Active quick tunnel:** `https://wendy-beliefs-directories-putting.trycloudflare.com`
- **Frontend build:** `frontend/dist` (Vite, served by FastAPI)

---

## 1. Completed Modules

### Module 1 — AI Template Generation

- **Endpoint:** `POST /api/v1/ai/generate-template`
- **Request:** `target_department`, `scenario`, optional `channel`
- **Response:** `subject`, `body_html`, `difficulty_level`, `provider`, `model`
- **Provider:** Dahl Inference, OpenAI-compatible API
  - Base URL: `https://inference.dahl.global/v1`
  - Model: `deepseek-ai/DeepSeek-V4-Flash-0731`
  - Key is configured in the ignored `backend/.env`; it is not committed.
- **Prompt context:** organization industry from the authenticated user's DB record, target department, scenario, and channel.
- **Safety:** generated HTML is sanitized (scripts, event handlers, dangerous URLs removed); output is validated before returning. Provider failures return explicit `502`; missing configuration returns explicit `503`. There is no mock fallback.
- **Authorization / limits:** admin and manager only; 10 requests per minute.
- **UI:** Create Template modal has the exact visible button **“✨ Generate with AI”**, loading state, error alert, and autofill for name, subject, body, channel, and difficulty.
- **Current live state:** a real **200** was observed once with Dahl: Arabic `subject`/`body_html`, `difficulty_level: 5`, model `deepseek-ai/DeepSeek-V4-Flash-0731`, ~90.4 seconds. Subsequent retries returned **HTTP 429 `model_concurrency`**; the provider admits signed-in/paid accounts first. Click **Allocate** in Dahl and retry for stable access. The backend timeout is 120 seconds and the frontend timeout is 150 seconds so the UI can receive a successful response.

### Module 2 — Elo Adaptive Difficulty

- **Field:** `human_assets.elo_score`, integer, default `1000`, backfilled by Alembic `0008_elo_rating`.
- **Deltas:** first click `-32`; first simulated report `+32`; repeated events do not double-apply.
- **Difficulty bands:**
  - `< 900` → Easy, template difficulty `1–3`
  - `900–1100` → Medium, template difficulty `4–7`
  - `> 1100` → Hard, template difficulty `8–10`
- **Threat badges:** Low `>= 1101`; Medium `900–1100`; High `800–899`; Critical `< 800`.
- **Launcher:** selects per recipient from active templates in the correct band and channel; rotates by `employee.total_tests_received`; falls back to the campaign template when the band has no candidate.
- **UI:** employee dossier shows `Elo` and a Low/Medium/High/Critical badge; campaign results show Elo, threat level, and delivered template difficulty.
- **Live selection probe:** employee Elo `1000` → band `medium`, range `(4, 7)`, selected `HR Portal · Employee Records Review` difficulty `4`; campaign fallback was `Urgent Password Change` difficulty `3`.
- **Live delta note:** existing live events predate the Elo migration, so all current employees are still at `1000`; delta behavior is covered by backend tests and will apply on the next real click/report.

### Module 3 — Simulated Attack-Chain Reveal

- Email click still opens `/phish/{uuid}` (the credential form).
- After form submission, the recipient is routed to `/hacked/{uuid}`.
- `/hacked/{uuid}` displays a terminal/Matrix typing sequence:
  - `Bypassing firewall...`
  - `Extracting credentials...`
  - `Accessing HR database...`
  - `Downloading 5GB of files...`
- After 5 seconds it interrupts with the red banner:
  - **“STOP! This was a simulation. In a real attack, your credentials would have caused this damage.”**
- A **“متابعة إلى التدريب”** CTA opens the training experience; there is no silent auto-redirect.
- Training page lists derived compromised assets with Arabic primary and English secondary labels, e.g.:
  - `كلمة مرور بريدك الإلكتروني` / `Your Email Password`
  - `الوصول إلى الأنظمة الداخلية المتاحة من حسابك` / `Access to Internal Systems`
- Assets are derived only after a real `submitted_at`; secrets are never returned. Live submitted context returns 4 assets; an unsubmitted tracking row returns 0.
- The terminal and red English banner are forced LTR inside the RTL app so they render correctly.

### Module 4 — Executive PDF Report

- **Endpoint:** `GET /api/v1/reports/executive-pdf?campaign_id={id}`
- **Authorization:** authenticated organization member (including viewer); campaign must belong to the user's organization, otherwise `404`.
- **PDF contents:**
  - Campaign summary and Arabic RTL text
  - Open/Click pie charts
  - Risky-department bar chart
  - Top 5 highest-risk employees by Elo, with department, threat level, clicks, and submissions
  - Arabic shaping with bundled Amiri fonts
- **Response:** `200 application/pdf`, `Content-Disposition: attachment`, `Cache-Control: no-store`.
- **UI:** Campaign Results page has **“Download Executive Report”**; live download produced a 47,096-byte, 2-page PDF.
- **Live verification:** Arabic text, pie charts, department chart, and top-5 table were extracted from the generated PDF; anonymous access `401`; unknown/foreign campaign `404`.

---

## 2. Verification Evidence

### Backend

```text
346 passed in 36.66s
Coverage: 89.67% (required 80%)
Alembic head: 0008_elo_rating
```

Run command:

```powershell
cd backend
python -m pytest -q
```

### Frontend

```text
Test Suites: 8 passed, 8 total
Tests:       28 passed, 28 total
Snapshots:   0 total
Time:        42.841 s
Ran all test suites.
```

Run command:

```powershell
cd frontend
npm run test
```

`npm run lint` and `npm run build` also pass. `frontend/dist` contains no temporary PDF/preview artifacts.

### Live endpoint checks

| Check | Result |
|---|---|
| `GET /healthz` local | `200 {"status":"ok","version":"1.0.0"}` |
| Public tunnel `/healthz` | `200 {"status":"ok","version":"1.0.0"}` |
| AI endpoint with Dahl key | `200` observed once — Arabic subject/body, `difficulty_level:5`, model `deepseek-ai/DeepSeek-V4-Flash-0731`; later retries `429 model_concurrency` |
| Brevo verify | `200` with `valid:false`, `action_required:ip_allowlist` |
| Draft campaign launch | `502` with exact IP-allowlist message; campaign remains `draft` |
| Executive PDF | `200 application/pdf`, 47,096 bytes, 2 pages |
| Submitted attack context | 4 compromised assets, no secrets |
| Unsubmitted attack context | 0 compromised assets |

---

## 3. Current Environment

- **Database:** SQLite at `backend/humint_dev.db`; Alembic revision `0008_elo_rating`.
- **PostgreSQL:** not available in this environment; SQLite is the active runtime.
- **Python:** 3.14.5. Python 3.11 is not installed.
- **AI:** Dahl key present in ignored `backend/.env`; a real `200` was observed, but subsequent retries return `429 model_concurrency` until the key is allocated/admitted. The model is slow (~90s per generation), so the backend timeout is 120s and the frontend timeout is 150s.
- **Email:** Brevo API key is present, but Brevo rejects the current egress IP. Current blocked IP: **`94.26.222.41`**.
- **SMS/WhatsApp:** Vonage API key/secret, WhatsApp sender/app credentials, and a test phone are blank. No real SMS/WhatsApp/DLR has been sent.
- **Tunnel:** Quick tunnel is active at `https://wendy-beliefs-directories-putting.trycloudflare.com`; it is ephemeral. The old `accepted-models-interval-ghz.trycloudflare.com` URL is dead.
- **Git:** CLI is available at `C:\Program Files\Git\cmd\git.exe` (not on PATH). `backend/.env`, databases, logs, and `frontend/dist` are ignored.
- **Secrets:** the Dahl key and other credentials exist only in the ignored `.env`; they are not included in this report or the commit.

---

## 4. Next Steps Checklist

- [x] **Dahl:** key is configured and a real `200` was observed with Arabic output and `difficulty_level: 5`.
- [ ] **Stabilize Dahl:** log in at `https://inference.dahl.global/account`, link this key, click **Allocate**, and retry until the AI endpoint returns `200` repeatably (latest retries are `429 model_concurrency`).
- [ ] **Brevo:** open Brevo → Security → Authorised IPs, add **`94.26.222.41`** (and `46.161.243.54` if that egress is still used), or disable the IP restriction.
- [ ] **Tunnel:** confirm the current quick tunnel or start a new `cloudflared tunnel --url http://localhost:8000`; update `BASE_URL` and `CORS_ORIGINS` in `backend/.env`; restart the backend.
- [ ] **Real email:** launch draft campaign `16ccfeb3-f986-46e9-956f-44b3f16e0883`.
- [ ] **Proof of life:** confirm delivery, click `/phish/{uuid}`, submit the form, observe `/hacked/{uuid}` for 5 seconds, then continue to training.
- [ ] **Database proof:** verify `submitted_at` is recorded and the employee's `elo_score` drops by 32 on first click.
- [ ] **PDF proof:** download the Executive PDF from Campaign Results.
- [ ] **Vonage:** configure API key/secret, SMS sender, WhatsApp sender/app credentials, webhooks, and a test phone; then test real SMS/WhatsApp/DLR.
- [ ] **Stable domain:** replace the ephemeral quick tunnel with a permanent domain before production.
- [ ] **Font license:** add the Amiri OFL license file if the bundled fonts will be distributed.
- [x] **Commit:** source changes and this report committed with `feat: complete AI, Elo, Hack, PDF + env cleanup + status report`.
- [ ] **Push:** push the commit to the remote when the remote is configured/available.

---

## 5. Known Limitations / Blockers

1. **Dahl access is intermittent.**
   A real generation returned `200` after ~90.4 seconds, but subsequent retries returned `429 model_concurrency`. The provider message says signed-in/paid accounts are admitted first and recommends allocating/linking the key, retrying after `Retry-After`, or switching models. Click **Allocate** for this key and retry. The backend timeout is 120s and the frontend timeout is 150s; no mock template is used as a fallback.

2. **Brevo IP allowlist is blocking email.**
   The current launch response is:

   ```json
   {
     "detail": "Real delivery is blocked: Your server IP is blocked by the email provider. Please allowlist it in your Brevo dashboard. Brevo reports the public IP as 94.26.222.41. Open Brevo → Security → Authorised IPs, add that address, or deactivate the IP restriction. Nothing else is blocking delivery."
   }
   ```

   The draft campaign remains `draft`; no email was sent.

3. **No real email/SMS/WhatsApp proof of life yet.**
   This depends on the Brevo allowlist and Vonage credentials above. The application paths are implemented and tested, but no real provider delivery has occurred.

4. **Quick tunnel is ephemeral.**
   The current URL works now but can die when the `cloudflared` process or session ends. A stable domain is required for production.

5. **Live Elo delta not observed on real data.**
   Existing employees are at `1000` because prior events predate the Elo migration. The first real post-migration click/report will apply `-32`/`+32`; backend tests already cover idempotency and boundaries.

6. **Adaptive template selection is per recipient at launch time.**
   The draft campaign's stored fallback template has difficulty `3`, but the launcher selected difficulty `4` for an Elo-1000 employee in the live probe. This is expected: the fallback is used only when the band has no candidate.

7. **Amiri font license file is not yet bundled.**
   The Amiri font files are present under `backend/app/assets/fonts`; add the OFL license file before redistribution.

8. **Git CLI is not on PATH.**
   Git is available at `C:\Program Files\Git\cmd\git.exe`; the commit was created with that full path. Add Git to PATH for convenience.

---

## 6. Operational Notes

- Restart the backend after changing `.env`; settings are loaded at startup.
- The main AI endpoint intentionally returns `503` when no key is configured and `502` when the provider fails; it never silently substitutes a mock template.
- AI generation is rate-limited to 10 requests/minute; PDF generation is rate-limited to 20 requests/minute.
- Dahl generation can take ~90s; the backend provider timeout is 120s and the frontend Axios timeout is 150s.
- `backend/.env`, `*.db`, `*.log`, and `frontend/dist/` are ignored and must not be committed.
- The active backend is serving the built frontend from `frontend/dist` at both the local and tunnel URLs.
