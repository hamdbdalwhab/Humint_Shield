# HUMINT Shield — Project Status

- **Last updated:** 2026-10-26
- **Branch:** `main`
- **Runtime:** Windows, Python 3.14.5, Node/Jest, SQLite
- **Local backend:** `http://127.0.0.1:8000`
- **Active quick tunnel:** `https://package-conferencing-bingo-successful.trycloudflare.com`
- **Frontend build:** `frontend/dist` (Vite, served by FastAPI)

---

## 1. Completed Modules

### Module 1 — AI Template Generation

- **Endpoint:** `POST /api/v1/ai/generate-template`
- **Request:** `target_department`, `scenario`, optional `channel`
- **Response:** `subject`, `body_html`, `difficulty_level`, `provider`, `model`
- **Provider:** Dahl Inference, OpenAI-compatible API
  - Base URL: `https://inference.dahl.global/v1`
  - Primary model: `deepseek-ai/DeepSeek-V4-Flash-0731`
  - Fallback model: `MiniMaxAI/MiniMax-M2.7` via `LLM_FALLBACK_MODELS`
  - Key is configured in the ignored `backend/.env`; it is not committed.
- **Prompt context:** organization industry from the authenticated user's DB record, target department, scenario, and channel.
- **Safety:** the model returns `body_text`; the backend escapes it and wraps it in a fixed, safe RTL HTML shell. If a model returns `body_html`, it is still sanitized (scripts, event handlers, dangerous URLs removed). Output is validated before returning. Provider failures return explicit **`424`** so Cloudflare passes the JSON error detail; missing configuration returns `503`. There is no mock template.
- **Cloudflare resilience:** the primary model has a 30-second budget, the fallback has 60 seconds, and the frontend Axios timeout is 150 seconds. A `429` or timeout from the primary transparently retries the fallback. This keeps normal generation inside Cloudflare's request window.
- **Authorization / limits:** admin and manager only; 10 requests per minute.
- **UI:** Create Template modal has the exact visible button **“✨ Generate with AI”**, loading state, error alert, and autofill for name, subject, body, channel, and difficulty.
- **Current live state (2026-10-26):** DeepSeek still returns **HTTP 429 `model_concurrency`**. The automatic fallback to MiniMax returned a real **`200` in 16.73 seconds** for `السكرتارية` + `تحديث كلمة المرور` with Arabic `subject`, valid RTL `body_html`, `difficulty_level: 5`, and `model: MiniMaxAI/MiniMax-M2.7`. The same generation was repeated from the browser UI: subject, body, and difficulty were autofilled and the previous Cloudflare error disappeared. Click **Allocate** in Dahl to restore DeepSeek as the preferred model.

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
350 passed in 39.32s
Coverage: 89.78% (required 80%)
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
| AI endpoint via public tunnel | `200` in `16.73s` — Arabic subject/body, `difficulty_level:5`, `model: MiniMaxAI/MiniMax-M2.7`; DeepSeek primary returned `429 model_concurrency` and fallback handled it |
| AI endpoint from browser UI | `200` — subject, body, and difficulty autofilled; no Cloudflare error |
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
- **AI:** Dahl key present in ignored `backend/.env`. Primary `deepseek-ai/DeepSeek-V4-Flash-0731` still returns `429 model_concurrency`; automatic fallback `MiniMaxAI/MiniMax-M2.7` is working. Primary timeout 30s, fallback timeout 60s, frontend timeout 150s.
- **Email:** Brevo API key is present, but Brevo rejects the current egress IP. Current blocked IP: **`94.26.222.41`**.
- **SMS/WhatsApp:** Vonage API key/secret, WhatsApp sender/app credentials, and a test phone are blank. No real SMS/WhatsApp/DLR has been sent.
- **Tunnel:** Quick tunnel is active at `https://package-conferencing-bingo-successful.trycloudflare.com`; it is ephemeral. Older quick-tunnel URLs (`wendy-beliefs-directories-putting`, `accepted-models-interval-ghz`) are dead.
- **Git:** CLI is available at `C:\Program Files\Git\cmd\git.exe` (not on PATH). `backend/.env`, databases, logs, and `frontend/dist` are ignored.
- **Secrets:** the Dahl key and other credentials exist only in the ignored `.env`; they are not included in this report or the commit.

---

## 4. Next Steps Checklist

- [x] **Dahl:** key is configured; primary DeepSeek still hits `429 model_concurrency`.
- [x] **Cloudflare 502 fix:** provider errors return `424`, primary has a 30s budget, and MiniMax fallback returns `200`; verified via the public tunnel and browser UI.
- [x] **AI fallback:** a real `200` in `16.73s` with Arabic subject/body, `difficulty_level: 5`, model `MiniMaxAI/MiniMax-M2.7`.
- [ ] **Stabilize Dahl primary:** log in at `https://inference.dahl.global/account`, link this key, click **Allocate**, and retry until DeepSeek returns `200` repeatably.
- [ ] **Brevo:** open Brevo → Security → Authorised IPs, add **`94.26.222.41`** (and `46.161.243.54` if that egress is still used), or disable the IP restriction.
- [x] **Tunnel:** current quick tunnel is active at `https://package-conferencing-bingo-successful.trycloudflare.com`; `BASE_URL`, `FRONTEND_URL`, and `CORS_ORIGINS` match it.
- [ ] **Real email:** launch draft campaign `16ccfeb3-f986-46e9-956f-44b3f16e0883` after Brevo allowlists the IP.
- [ ] **Proof of life:** confirm delivery, click `/phish/{uuid}`, submit the form, observe `/hacked/{uuid}` for 5 seconds, then continue to training.
- [ ] **Database proof:** verify `submitted_at` is recorded and the employee's `elo_score` drops by 32 on first click.
- [ ] **PDF proof:** download the Executive PDF from Campaign Results.
- [ ] **Vonage:** configure API key/secret, SMS sender, WhatsApp sender/app credentials, webhooks, and a test phone; then test real SMS/WhatsApp/DLR.
- [ ] **Stable domain:** replace the ephemeral quick tunnel with a permanent domain before production.
- [ ] **Font license:** add the Amiri OFL license file if the bundled fonts will be distributed.
- [x] **Commit:** previous production-readiness work committed as `76c2d86`.
- [x] **Commit this fix:** `b6ab0ba` — AI fallback / Cloudflare fix.
- [ ] **Push:** `main` is ahead of `origin/main` by 4 commits; push when confirmed.

---

## 5. Known Limitations / Blockers

1. **Dahl primary model is capacity-limited; fallback is active.**
   DeepSeek returns `429 model_concurrency`; the provider admits signed-in/paid accounts first. The service now automatically falls back to MiniMax and returns a real template. Click **Allocate** for this key at `https://inference.dahl.global/account` to restore DeepSeek as the preferred model. No mock template is used; both primary and fallback are real providers. MiniMax may take 15–50 seconds and emits a reasoning block, which the parser strips before validating the JSON.

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
- The main AI endpoint intentionally returns `503` when no key is configured and **`424`** when the provider fails; it never silently substitutes a mock template. The `424` is deliberate: Cloudflare replaces origin `5xx` responses with its own HTML error page, which hid the actionable provider message.
- AI generation is rate-limited to 10 requests/minute; PDF generation is rate-limited to 20 requests/minute.
- Primary AI timeout is 30s; fallback timeout is 60s; the frontend Axios timeout is 150s. Keep the combined primary + fallback budget below Cloudflare's request window.
- `backend/.env`, `*.db`, `*.log`, and `frontend/dist/` are ignored and must not be committed.
- The active backend is serving the built frontend from `frontend/dist` at both the local and tunnel URLs.
- Current runtime PIDs: backend `9500`, cloudflared `16252` (verify after any restart).
